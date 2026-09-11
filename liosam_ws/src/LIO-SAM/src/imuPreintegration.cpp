#include "utility.h"

#include <gtsam/geometry/Rot3.h>
#include <gtsam/geometry/Pose3.h>
#include <gtsam/slam/PriorFactor.h>
#include <gtsam/slam/BetweenFactor.h>
#include <gtsam/navigation/GPSFactor.h>
#include <gtsam/navigation/ImuFactor.h>
#include <gtsam/navigation/ImuFactorWithGravity.h>
#include <gtsam/navigation/CombinedImuFactor.h>
#include <gtsam/nonlinear/NonlinearFactorGraph.h>
#include <gtsam/nonlinear/LevenbergMarquardtOptimizer.h>
#include <gtsam/nonlinear/Marginals.h>
#include <gtsam/nonlinear/Values.h>
#include <gtsam/inference/Symbol.h>

#include <gtsam/nonlinear/ISAM2.h>

#include <fstream>
#include <iomanip>
#include <cstdint>

#include "lio_sam/ImuAblationFactors.h"

#ifndef LIOSAM_ESTIMATE_GRAVITY
#define LIOSAM_ESTIMATE_GRAVITY 0
#endif

#ifndef LIOSAM_ESTIMATE_ACCEL_BIAS
#define LIOSAM_ESTIMATE_ACCEL_BIAS 1
#endif

#ifndef LIOSAM_ENABLE_GRAVITY_DIRECTION
#define LIOSAM_ENABLE_GRAVITY_DIRECTION 0
#endif

static_assert(LIOSAM_ESTIMATE_GRAVITY == 0 || LIOSAM_ESTIMATE_GRAVITY == 1,
              "LIOSAM_ESTIMATE_GRAVITY must be 0 or 1");
static_assert(LIOSAM_ESTIMATE_ACCEL_BIAS == 0 ||
                  LIOSAM_ESTIMATE_ACCEL_BIAS == 1,
              "LIOSAM_ESTIMATE_ACCEL_BIAS must be 0 or 1");
static_assert(LIOSAM_ENABLE_GRAVITY_DIRECTION == 0 ||
                  LIOSAM_ENABLE_GRAVITY_DIRECTION == 1,
              "LIOSAM_ENABLE_GRAVITY_DIRECTION must be 0 or 1");

using gtsam::symbol_shorthand::X; // Pose3 (x,y,z,r,p,y)
using gtsam::symbol_shorthand::V; // Vel   (xdot,ydot,zdot)
using gtsam::symbol_shorthand::B; // Bias  (ax,ay,az,gx,gy,gz)

#if LIOSAM_ESTIMATE_ACCEL_BIAS
using OptimizedBias = gtsam::imuBias::ConstantBias;
#else
using OptimizedBias = gtsam::Vector3;  // gyroscope bias only
#endif

namespace {

gtsam::Key gravityKey()
{
    return gtsam::Symbol('g', 0);
}

const char* ablationVariantName()
{
#if LIOSAM_ESTIMATE_GRAVITY && LIOSAM_ESTIMATE_ACCEL_BIAS
    return "GE-BA";
#elif LIOSAM_ESTIMATE_GRAVITY && !LIOSAM_ESTIMATE_ACCEL_BIAS
    return "GE-B0";
#elif !LIOSAM_ESTIMATE_GRAVITY && LIOSAM_ESTIMATE_ACCEL_BIAS
    return "FG-BA";
#else
    return "FG-B0";
#endif
}

OptimizedBias optimizedBiasFromFull(
    const gtsam::imuBias::ConstantBias& fullBias)
{
#if LIOSAM_ESTIMATE_ACCEL_BIAS
    return fullBias;
#else
    return fullBias.gyroscope();
#endif
}

gtsam::imuBias::ConstantBias fullBiasFromOptimized(
    const OptimizedBias& optimizedBias, const gtsam::Vector3& fixedAccelBias)
{
#if LIOSAM_ESTIMATE_ACCEL_BIAS
    (void)fixedAccelBias;
    return optimizedBias;
#else
    return gtsam::imuBias::ConstantBias(fixedAccelBias, optimizedBias);
#endif
}

OptimizedBias zeroOptimizedBias()
{
#if LIOSAM_ESTIMATE_ACCEL_BIAS
    return gtsam::imuBias::ConstantBias();
#else
    return gtsam::Vector3::Zero();
#endif
}

}  // namespace

class TransformFusion : public ParamServer
{
public:
    std::mutex mtx;

    ros::Subscriber subImuOdometry;
    ros::Subscriber subLaserOdometry;

    ros::Publisher pubImuOdometry;
    ros::Publisher pubImuPath;

    Eigen::Affine3f lidarOdomAffine;
    Eigen::Affine3f imuOdomAffineFront;
    Eigen::Affine3f imuOdomAffineBack;

    tf::TransformListener tfListener;
    tf::StampedTransform lidar2Baselink;

    double lidarOdomTime = -1;
    deque<nav_msgs::Odometry> imuOdomQueue;

    TransformFusion()
    {
        if(lidarFrame != baselinkFrame)
        {
            try
            {
                tfListener.waitForTransform(lidarFrame, baselinkFrame, ros::Time(0), ros::Duration(3.0));
                tfListener.lookupTransform(lidarFrame, baselinkFrame, ros::Time(0), lidar2Baselink);
            }
            catch (tf::TransformException ex)
            {
                ROS_ERROR("%s",ex.what());
            }
        }

        subLaserOdometry = nh.subscribe<nav_msgs::Odometry>("lio_sam/mapping/odometry", 5, &TransformFusion::lidarOdometryHandler, this, ros::TransportHints().tcpNoDelay());
        subImuOdometry   = nh.subscribe<nav_msgs::Odometry>(odomTopic+"_incremental",   2000, &TransformFusion::imuOdometryHandler,   this, ros::TransportHints().tcpNoDelay());

        pubImuOdometry   = nh.advertise<nav_msgs::Odometry>(odomTopic, 2000);
        pubImuPath       = nh.advertise<nav_msgs::Path>    ("lio_sam/imu/path", 1);
    }

    Eigen::Affine3f odom2affine(nav_msgs::Odometry odom)
    {
        double x, y, z, roll, pitch, yaw;
        x = odom.pose.pose.position.x;
        y = odom.pose.pose.position.y;
        z = odom.pose.pose.position.z;
        tf::Quaternion orientation;
        tf::quaternionMsgToTF(odom.pose.pose.orientation, orientation);
        tf::Matrix3x3(orientation).getRPY(roll, pitch, yaw);
        return pcl::getTransformation(x, y, z, roll, pitch, yaw);
    }

    void lidarOdometryHandler(const nav_msgs::Odometry::ConstPtr& odomMsg)
    {
        std::lock_guard<std::mutex> lock(mtx);

        lidarOdomAffine = odom2affine(*odomMsg);

        lidarOdomTime = odomMsg->header.stamp.toSec();
    }

    void imuOdometryHandler(const nav_msgs::Odometry::ConstPtr& odomMsg)
    {
        // static tf
        static tf::TransformBroadcaster tfMap2Odom;
        static tf::Transform map_to_odom = tf::Transform(tf::createQuaternionFromRPY(0, 0, 0), tf::Vector3(0, 0, 0));
        tfMap2Odom.sendTransform(tf::StampedTransform(map_to_odom, odomMsg->header.stamp, mapFrame, odometryFrame));

        std::lock_guard<std::mutex> lock(mtx);

        imuOdomQueue.push_back(*odomMsg);

        // get latest odometry (at current IMU stamp)
        if (lidarOdomTime == -1)
            return;
        while (!imuOdomQueue.empty())
        {
            if (imuOdomQueue.front().header.stamp.toSec() <= lidarOdomTime)
                imuOdomQueue.pop_front();
            else
                break;
        }
        Eigen::Affine3f imuOdomAffineFront = odom2affine(imuOdomQueue.front());
        Eigen::Affine3f imuOdomAffineBack = odom2affine(imuOdomQueue.back());
        Eigen::Affine3f imuOdomAffineIncre = imuOdomAffineFront.inverse() * imuOdomAffineBack;
        Eigen::Affine3f imuOdomAffineLast = lidarOdomAffine * imuOdomAffineIncre;
        float x, y, z, roll, pitch, yaw;
        pcl::getTranslationAndEulerAngles(imuOdomAffineLast, x, y, z, roll, pitch, yaw);
        
        // publish latest odometry
        nav_msgs::Odometry laserOdometry = imuOdomQueue.back();
        laserOdometry.pose.pose.position.x = x;
        laserOdometry.pose.pose.position.y = y;
        laserOdometry.pose.pose.position.z = z;
        laserOdometry.pose.pose.orientation = tf::createQuaternionMsgFromRollPitchYaw(roll, pitch, yaw);
        pubImuOdometry.publish(laserOdometry);

        // publish tf
        static tf::TransformBroadcaster tfOdom2BaseLink;
        tf::Transform tCur;
        tf::poseMsgToTF(laserOdometry.pose.pose, tCur);
        if(lidarFrame != baselinkFrame)
            tCur = tCur * lidar2Baselink;
        tf::StampedTransform odom_2_baselink = tf::StampedTransform(tCur, odomMsg->header.stamp, odometryFrame, baselinkFrame);
        tfOdom2BaseLink.sendTransform(odom_2_baselink);

        // publish IMU path
        static nav_msgs::Path imuPath;
        static double last_path_time = -1;
        double imuTime = imuOdomQueue.back().header.stamp.toSec();
        if (imuTime - last_path_time > 0.1)
        {
            last_path_time = imuTime;
            geometry_msgs::PoseStamped pose_stamped;
            pose_stamped.header.stamp = imuOdomQueue.back().header.stamp;
            pose_stamped.header.frame_id = odometryFrame;
            pose_stamped.pose = laserOdometry.pose.pose;
            imuPath.poses.push_back(pose_stamped);
            while(!imuPath.poses.empty() && imuPath.poses.front().header.stamp.toSec() < lidarOdomTime - 1.0)
                imuPath.poses.erase(imuPath.poses.begin());
            if (pubImuPath.getNumSubscribers() != 0)
            {
                imuPath.header.stamp = imuOdomQueue.back().header.stamp;
                imuPath.header.frame_id = odometryFrame;
                pubImuPath.publish(imuPath);
            }
        }
    }
};

class IMUPreintegration : public ParamServer
{
public:

    std::mutex mtx;

    ros::Subscriber subImu;
    ros::Subscriber subOdometry;
    ros::Publisher pubImuOdometry;

    bool systemInitialized = false;

    gtsam::noiseModel::Diagonal::shared_ptr priorPoseNoise;
    gtsam::noiseModel::Diagonal::shared_ptr priorVelNoise;
    gtsam::noiseModel::Diagonal::shared_ptr priorBiasNoise;
    gtsam::noiseModel::Diagonal::shared_ptr correctionNoise;
    gtsam::noiseModel::Diagonal::shared_ptr correctionNoise2;
    gtsam::Vector noiseModelBetweenBias;

    const gtsam::Vector3 fixedAccelBias_ = gtsam::Vector3::Zero();
    gtsam::Vector3 fixedGravity_ = gtsam::Vector3(0.0, 0.0, -9.81);
    gtsam::Unit3 prevGravity_ = gtsam::Unit3(fixedGravity_);
    double gravityMagnitude_ = 9.81;
    double initialGravityPriorSigma_ = M_PI / 6.0;
    bool gravityInGraph_ = false;

#if LIOSAM_ENABLE_GRAVITY_DIRECTION
    double gravityDirectionSigma_ = -1.0;
    gtsam::SharedNoiseModel gravityDirectionNoise_;
    std::uint64_t gravityDirectionFactorCount_ = 0;
    std::ofstream gravityDirectionLog_;
    std::string gravityDirectionLogPath_;
#endif

    std::ofstream stateLog_;
    std::string stateLogPath_;

    gtsam::PreintegratedImuMeasurements *imuIntegratorOpt_;
    gtsam::PreintegratedImuMeasurements *imuIntegratorImu_;

    std::deque<sensor_msgs::Imu> imuQueOpt;
    std::deque<sensor_msgs::Imu> imuQueImu;

    gtsam::Pose3 prevPose_;
    gtsam::Vector3 prevVel_;
    gtsam::NavState prevState_;
    gtsam::imuBias::ConstantBias prevBias_;

    gtsam::NavState prevStateOdom;
    gtsam::imuBias::ConstantBias prevBiasOdom;

    bool doneFirstOpt = false;
    double lastImuT_imu = -1;
    double lastImuT_opt = -1;

    gtsam::ISAM2 optimizer;
    gtsam::NonlinearFactorGraph graphFactors;
    gtsam::Values graphValues;

    const double delta_t = 0;

    int key = 1;
    
    // T_bl: tramsform points from lidar frame to imu frame 
    gtsam::Pose3 imu2Lidar = gtsam::Pose3(gtsam::Rot3(1, 0, 0, 0), gtsam::Point3(-extTrans.x(), -extTrans.y(), -extTrans.z()));
    // T_lb: tramsform points from imu frame to lidar frame
    gtsam::Pose3 lidar2Imu = gtsam::Pose3(gtsam::Rot3(1, 0, 0, 0), gtsam::Point3(extTrans.x(), extTrans.y(), extTrans.z()));

    IMUPreintegration()
    {
        subImu      = nh.subscribe<sensor_msgs::Imu>  (imuTopic,                   2000, &IMUPreintegration::imuHandler,      this, ros::TransportHints().tcpNoDelay());
        subOdometry = nh.subscribe<nav_msgs::Odometry>("lio_sam/mapping/odometry_incremental", 5,    &IMUPreintegration::odometryHandler, this, ros::TransportHints().tcpNoDelay());

        pubImuOdometry = nh.advertise<nav_msgs::Odometry> (odomTopic+"_incremental", 2000);

        std::shared_ptr<gtsam::PreintegrationParams> p = gtsam::PreintegrationParams::MakeSharedU(imuGravity);
        p->accelerometerCovariance  = gtsam::Matrix33::Identity(3,3) * pow(imuAccNoise, 2); // acc white noise in continuous
        p->gyroscopeCovariance      = gtsam::Matrix33::Identity(3,3) * pow(imuGyrNoise, 2); // gyro white noise in continuous
        p->integrationCovariance    = gtsam::Matrix33::Identity(3,3) * pow(1e-4, 2); // error committed in integrating position from velocities
        fixedGravity_ = p->n_gravity;
        prevGravity_ = gtsam::Unit3(fixedGravity_);
        gravityMagnitude_ = fixedGravity_.norm();
        gtsam::imuBias::ConstantBias prior_imu_bias((gtsam::Vector(6) << 0, 0, 0, 0, 0, 0).finished());; // assume zero initial bias

        priorPoseNoise  = gtsam::noiseModel::Diagonal::Sigmas((gtsam::Vector(6) << 1e-2, 1e-2, 1e-2, 1e-2, 1e-2, 1e-2).finished()); // rad,rad,rad,m, m, m
        priorVelNoise   = gtsam::noiseModel::Isotropic::Sigma(3, 1e4); // m/s
#if LIOSAM_ESTIMATE_ACCEL_BIAS
        priorBiasNoise  = gtsam::noiseModel::Isotropic::Sigma(6, 1e-3); // 1e-2 ~ 1e-3 seems to be good
#else
        priorBiasNoise  = gtsam::noiseModel::Isotropic::Sigma(3, 1e-3);
#endif
        correctionNoise = gtsam::noiseModel::Diagonal::Sigmas((gtsam::Vector(6) << 0.05, 0.05, 0.05, 0.1, 0.1, 0.1).finished()); // rad,rad,rad,m, m, m
        correctionNoise2 = gtsam::noiseModel::Diagonal::Sigmas((gtsam::Vector(6) << 1, 1, 1, 1, 1, 1).finished()); // rad,rad,rad,m, m, m
#if LIOSAM_ESTIMATE_ACCEL_BIAS
        noiseModelBetweenBias = (gtsam::Vector(6) << imuAccBiasN, imuAccBiasN, imuAccBiasN, imuGyrBiasN, imuGyrBiasN, imuGyrBiasN).finished();
#else
        noiseModelBetweenBias = (gtsam::Vector(3) << imuGyrBiasN, imuGyrBiasN, imuGyrBiasN).finished();
#endif
        
        imuIntegratorImu_ = new gtsam::PreintegratedImuMeasurements(p, prior_imu_bias); // setting up the IMU integration for IMU message thread
        imuIntegratorOpt_ = new gtsam::PreintegratedImuMeasurements(p, prior_imu_bias); // setting up the IMU integration for optimization        

        nh.param<std::string>("lio_sam/ablationLogPath", stateLogPath_, "");
        nh.param<double>("lio_sam/gravityPriorSigma",
                         initialGravityPriorSigma_, M_PI / 6.0);
#if LIOSAM_ENABLE_GRAVITY_DIRECTION
        nh.param<double>("lio_sam/gravityDirectionSigma",
                         gravityDirectionSigma_, -1.0);
        nh.param<std::string>("lio_sam/gravityDirectionLogPath",
                              gravityDirectionLogPath_, "");
        if (gravityDirectionSigma_ > 0.0)
        {
            gravityDirectionNoise_ = gtsam::noiseModel::Isotropic::Sigma(
                2, gravityDirectionSigma_);
        }
        if (!gravityDirectionLogPath_.empty())
        {
            gravityDirectionLog_.open(
                gravityDirectionLogPath_, std::ios::out | std::ios::trunc);
            if (!gravityDirectionLog_)
            {
                ROS_ERROR_STREAM("Cannot open gravity direction log: "
                                 << gravityDirectionLogPath_);
            }
            else
            {
                gravityDirectionLog_
                    << "timestamp,key,variant,factor_index,measurement_age_s,"
                       "pre_residual_deg,post_residual_deg\n";
                gravityDirectionLog_ << std::setprecision(17);
            }
        }
#endif
        if (!stateLogPath_.empty())
        {
            stateLog_.open(stateLogPath_, std::ios::out | std::ios::trunc);
            if (!stateLog_)
            {
                ROS_ERROR_STREAM("Cannot open ablation state log: " << stateLogPath_);
            }
            else
            {
                stateLog_ << "timestamp,key,variant,px,py,pz,vx,vy,vz,"
                             "bax,bay,baz,bgx,bgy,bgz,gx,gy,gz\n";
                stateLog_ << std::setprecision(17);
            }
        }

        ROS_INFO_STREAM("LIO-SAM ablation structure: " << ablationVariantName()
                        << ", estimate_g=" << LIOSAM_ESTIMATE_GRAVITY
                        << ", estimate_ba=" << LIOSAM_ESTIMATE_ACCEL_BIAS
                        << ", gravity_norm=" << gravityMagnitude_
#if LIOSAM_ENABLE_GRAVITY_DIRECTION
                        << ", gravity_direction_sigma="
                        << gravityDirectionSigma_
#else
                        << ", gravity_direction=not_compiled"
#endif
                        );
    }

    void resetOptimization()
    {
        gtsam::ISAM2Params optParameters;
        optParameters.relinearizeThreshold = 0.1;
        optParameters.relinearizeSkip = 1;
        optimizer = gtsam::ISAM2(optParameters);

        gtsam::NonlinearFactorGraph newGraphFactors;
        graphFactors = newGraphFactors;

        gtsam::Values NewGraphValues;
        graphValues = NewGraphValues;

        gravityInGraph_ = false;
    }

    void resetParams()
    {
        lastImuT_imu = -1;
        doneFirstOpt = false;
        systemInitialized = false;
    }

    void addBiasPrior(gtsam::Key biasKey,
                      const gtsam::SharedNoiseModel& noise)
    {
        graphFactors.add(gtsam::PriorFactor<OptimizedBias>(
            biasKey, optimizedBiasFromFull(prevBias_), noise));
    }

    void insertBiasValue(gtsam::Key biasKey)
    {
        graphValues.insert(biasKey, optimizedBiasFromFull(prevBias_));
    }

    void addBiasRandomWalkFactor(gtsam::Key previousBiasKey,
                                 gtsam::Key currentBiasKey)
    {
        graphFactors.add(gtsam::BetweenFactor<OptimizedBias>(
            previousBiasKey, currentBiasKey, zeroOptimizedBias(),
            gtsam::noiseModel::Diagonal::Sigmas(
                sqrt(imuIntegratorOpt_->deltaTij()) *
                noiseModelBetweenBias)));
    }

    void updateBiasFromResult(const gtsam::Values& result,
                              gtsam::Key biasKey)
    {
        prevBias_ = fullBiasFromOptimized(
            result.at<OptimizedBias>(biasKey), fixedAccelBias_);
    }

    gtsam::Vector3 currentGravityVector() const
    {
#if LIOSAM_ESTIMATE_GRAVITY
        return prevGravity_.unitVector() * gravityMagnitude_;
#else
        return fixedGravity_;
#endif
    }

    void addImuFactor(
        const gtsam::PreintegratedImuMeasurements& preintegrated)
    {
#if LIOSAM_ESTIMATE_GRAVITY
        if (!gravityInGraph_)
        {
            graphFactors.add(gtsam::PriorFactor<gtsam::Unit3>(
                gravityKey(), prevGravity_,
                gtsam::noiseModel::Isotropic::Sigma(
                    2, initialGravityPriorSigma_)));
            graphValues.insert(gravityKey(), prevGravity_);
            gravityInGraph_ = true;
        }
#if LIOSAM_ESTIMATE_ACCEL_BIAS
        graphFactors.add(gtsam::ImuFactorWithGravityDirection(
            X(key - 1), V(key - 1), X(key), V(key), B(key - 1),
            gravityKey(), preintegrated, gravityMagnitude_));
#else
        graphFactors.add(
            lio_sam_ablation::ImuFactorWithGravityFixedAccelBias(
                X(key - 1), V(key - 1), X(key), V(key), B(key - 1),
                gravityKey(), preintegrated, fixedAccelBias_,
                gravityMagnitude_));
#endif
#else
#if LIOSAM_ESTIMATE_ACCEL_BIAS
        graphFactors.add(gtsam::ImuFactor(
            X(key - 1), V(key - 1), X(key), V(key), B(key - 1),
            preintegrated));
#else
        graphFactors.add(lio_sam_ablation::ImuFactorFixedAccelBias(
            X(key - 1), V(key - 1), X(key), V(key), B(key - 1),
            preintegrated, fixedAccelBias_));
#endif
#endif
    }

#if LIOSAM_ENABLE_GRAVITY_DIRECTION
    bool gravityDirectionMeasurement(
        const sensor_msgs::Imu& imu, gtsam::Unit3* measurement) const
    {
        if (imu.orientation_covariance[0] < 0.0)
            return false;

        const double qx = imu.orientation.x;
        const double qy = imu.orientation.y;
        const double qz = imu.orientation.z;
        const double qw = imu.orientation.w;
        const double norm = std::sqrt(qx * qx + qy * qy + qz * qz + qw * qw);
        if (!std::isfinite(norm) || norm < 0.1)
            return false;

        const gtsam::Rot3 bodyToWorld = gtsam::Rot3::Quaternion(
            qw / norm, qx / norm, qy / norm, qz / norm);
        *measurement = bodyToWorld.unrotate(gtsam::Unit3(fixedGravity_));
        return measurement->unitVector().allFinite();
    }

    double gravityDirectionResidualDeg(
        const gtsam::Pose3& pose, const gtsam::Unit3& gravityWorld,
        const gtsam::Unit3& measuredGravityBody) const
    {
        const gtsam::Unit3 predictedBody =
            pose.rotation().unrotate(gravityWorld);
        return measuredGravityBody.distance(predictedBody) * 180.0 / M_PI;
    }

    void addGravityDirectionFactor(
        const gtsam::Unit3& measuredGravityBody)
    {
#if LIOSAM_ESTIMATE_GRAVITY
        graphFactors.add(
            lio_sam_ablation::GravityDirectionFactorEstimated(
                X(key), gravityKey(), measuredGravityBody,
                gravityDirectionNoise_));
#else
        graphFactors.add(lio_sam_ablation::GravityDirectionFactorFixed(
            X(key), gtsam::Unit3(fixedGravity_), measuredGravityBody,
            gravityDirectionNoise_));
#endif
        ++gravityDirectionFactorCount_;
    }

    void logGravityDirectionFactor(
        double timestamp, double measurementAge,
        double preResidualDeg, double postResidualDeg)
    {
        if (!gravityDirectionLog_)
            return;
        gravityDirectionLog_ << timestamp << ',' << key << ','
                             << ablationVariantName() << ','
                             << gravityDirectionFactorCount_ << ','
                             << measurementAge << ',' << preResidualDeg << ','
                             << postResidualDeg << '\n';
        gravityDirectionLog_.flush();
    }
#endif

    gtsam::NavState predictState(
        const gtsam::PreintegratedImuMeasurements* integrator,
        const gtsam::NavState& state,
        const gtsam::imuBias::ConstantBias& bias) const
    {
#if LIOSAM_ESTIMATE_GRAVITY
        return integrator->predict(state, bias, currentGravityVector());
#else
        return integrator->predict(state, bias);
#endif
    }

    void logOptimizedState(double timestamp)
    {
        if (!stateLog_)
            return;

        const gtsam::Vector3 ba = prevBias_.accelerometer();
        const gtsam::Vector3 bg = prevBias_.gyroscope();
        const gtsam::Vector3 gravity = currentGravityVector();
        stateLog_ << timestamp << ',' << key << ',' << ablationVariantName()
                  << ',' << prevPose_.x() << ',' << prevPose_.y() << ','
                  << prevPose_.z() << ',' << prevVel_.x() << ','
                  << prevVel_.y() << ',' << prevVel_.z() << ',' << ba.x()
                  << ',' << ba.y() << ',' << ba.z() << ',' << bg.x() << ','
                  << bg.y() << ',' << bg.z() << ',' << gravity.x() << ','
                  << gravity.y() << ',' << gravity.z() << '\n';
        stateLog_.flush();
    }

    void odometryHandler(const nav_msgs::Odometry::ConstPtr& odomMsg)
    {
        std::lock_guard<std::mutex> lock(mtx);

        double currentCorrectionTime = ROS_TIME(odomMsg);

        // make sure we have imu data to integrate
        if (imuQueOpt.empty())
            return;

        float p_x = odomMsg->pose.pose.position.x;
        float p_y = odomMsg->pose.pose.position.y;
        float p_z = odomMsg->pose.pose.position.z;
        float r_x = odomMsg->pose.pose.orientation.x;
        float r_y = odomMsg->pose.pose.orientation.y;
        float r_z = odomMsg->pose.pose.orientation.z;
        float r_w = odomMsg->pose.pose.orientation.w;
        bool degenerate = (int)odomMsg->pose.covariance[0] == 1 ? true : false;
        gtsam::Pose3 lidarPose = gtsam::Pose3(gtsam::Rot3::Quaternion(r_w, r_x, r_y, r_z), gtsam::Point3(p_x, p_y, p_z));


        // 0. initialize system
        if (systemInitialized == false)
        {
            resetOptimization();

            // pop old IMU message
            while (!imuQueOpt.empty())
            {
                if (ROS_TIME(&imuQueOpt.front()) < currentCorrectionTime - delta_t)
                {
                    lastImuT_opt = ROS_TIME(&imuQueOpt.front());
                    imuQueOpt.pop_front();
                }
                else
                    break;
            }
            // initial pose
            prevPose_ = lidarPose.compose(lidar2Imu);
            gtsam::PriorFactor<gtsam::Pose3> priorPose(X(0), prevPose_, priorPoseNoise);
            graphFactors.add(priorPose);
            // initial velocity
            prevVel_ = gtsam::Vector3(0, 0, 0);
            gtsam::PriorFactor<gtsam::Vector3> priorVel(V(0), prevVel_, priorVelNoise);
            graphFactors.add(priorVel);
            // initial bias
            prevBias_ = gtsam::imuBias::ConstantBias();
            prevGravity_ = gtsam::Unit3(fixedGravity_);
            addBiasPrior(B(0), priorBiasNoise);
            // add values
            graphValues.insert(X(0), prevPose_);
            graphValues.insert(V(0), prevVel_);
            insertBiasValue(B(0));
            // optimize once
            optimizer.update(graphFactors, graphValues);
            graphFactors.resize(0);
            graphValues.clear();

            imuIntegratorImu_->resetIntegrationAndSetBias(prevBias_);
            imuIntegratorOpt_->resetIntegrationAndSetBias(prevBias_);
            
            key = 1;
            systemInitialized = true;
            return;
        }


        // reset graph for speed
        if (key == 100)
        {
            // get updated noise before reset
            gtsam::noiseModel::Gaussian::shared_ptr updatedPoseNoise = gtsam::noiseModel::Gaussian::Covariance(optimizer.marginalCovariance(X(key-1)));
            gtsam::noiseModel::Gaussian::shared_ptr updatedVelNoise  = gtsam::noiseModel::Gaussian::Covariance(optimizer.marginalCovariance(V(key-1)));
            gtsam::noiseModel::Gaussian::shared_ptr updatedBiasNoise = gtsam::noiseModel::Gaussian::Covariance(optimizer.marginalCovariance(B(key-1)));
#if LIOSAM_ESTIMATE_GRAVITY
            gtsam::noiseModel::Gaussian::shared_ptr updatedGravityNoise =
                gtsam::noiseModel::Gaussian::Covariance(
                    optimizer.marginalCovariance(gravityKey()));
#endif
            // reset graph
            resetOptimization();
            // add pose
            gtsam::PriorFactor<gtsam::Pose3> priorPose(X(0), prevPose_, updatedPoseNoise);
            graphFactors.add(priorPose);
            // add velocity
            gtsam::PriorFactor<gtsam::Vector3> priorVel(V(0), prevVel_, updatedVelNoise);
            graphFactors.add(priorVel);
            // add bias
            addBiasPrior(B(0), updatedBiasNoise);
#if LIOSAM_ESTIMATE_GRAVITY
            graphFactors.add(gtsam::PriorFactor<gtsam::Unit3>(
                gravityKey(), prevGravity_, updatedGravityNoise));
#endif
            // add values
            graphValues.insert(X(0), prevPose_);
            graphValues.insert(V(0), prevVel_);
            insertBiasValue(B(0));
#if LIOSAM_ESTIMATE_GRAVITY
            graphValues.insert(gravityKey(), prevGravity_);
            gravityInGraph_ = true;
#endif
            // optimize once
            optimizer.update(graphFactors, graphValues);
            graphFactors.resize(0);
            graphValues.clear();

            key = 1;
        }


        // 1. integrate imu data and optimize
#if LIOSAM_ENABLE_GRAVITY_DIRECTION
        sensor_msgs::Imu directionImu;
        bool haveDirectionImu = false;
#endif
        while (!imuQueOpt.empty())
        {
            // pop and integrate imu data that is between two optimizations
            sensor_msgs::Imu *thisImu = &imuQueOpt.front();
            double imuTime = ROS_TIME(thisImu);
            if (imuTime < currentCorrectionTime - delta_t)
            {
                double dt = (lastImuT_opt < 0) ? (1.0 / 500.0) : (imuTime - lastImuT_opt);
                imuIntegratorOpt_->integrateMeasurement(
                        gtsam::Vector3(thisImu->linear_acceleration.x, thisImu->linear_acceleration.y, thisImu->linear_acceleration.z),
                        gtsam::Vector3(thisImu->angular_velocity.x,    thisImu->angular_velocity.y,    thisImu->angular_velocity.z), dt);

#if LIOSAM_ENABLE_GRAVITY_DIRECTION
                directionImu = *thisImu;
                haveDirectionImu = true;
#endif
                lastImuT_opt = imuTime;
                imuQueOpt.pop_front();
            }
            else
                break;
        }
        // add imu factor to graph
        const gtsam::PreintegratedImuMeasurements& preint_imu = dynamic_cast<const gtsam::PreintegratedImuMeasurements&>(*imuIntegratorOpt_);
        addImuFactor(preint_imu);
        // add imu bias between factor
        addBiasRandomWalkFactor(B(key - 1), B(key));
        // add pose factor
        gtsam::Pose3 curPose = lidarPose.compose(lidar2Imu);
        gtsam::PriorFactor<gtsam::Pose3> pose_factor(X(key), curPose, degenerate ? correctionNoise2 : correctionNoise);
        graphFactors.add(pose_factor);
        // insert predicted values
        gtsam::NavState propState_ = predictState(imuIntegratorOpt_, prevState_, prevBias_);
        graphValues.insert(X(key), propState_.pose());
        graphValues.insert(V(key), propState_.v());
        insertBiasValue(B(key));
#if LIOSAM_ENABLE_GRAVITY_DIRECTION
        gtsam::Unit3 measuredGravityBody;
        bool addedGravityDirectionFactor = false;
        double gravityDirectionMeasurementAge = 0.0;
        double gravityDirectionPreResidualDeg = 0.0;
        if (gravityDirectionSigma_ > 0.0 && haveDirectionImu &&
            gravityDirectionMeasurement(directionImu, &measuredGravityBody))
        {
            gravityDirectionMeasurementAge =
                currentCorrectionTime - ROS_TIME(&directionImu);
            gravityDirectionPreResidualDeg = gravityDirectionResidualDeg(
                propState_.pose(),
#if LIOSAM_ESTIMATE_GRAVITY
                prevGravity_,
#else
                gtsam::Unit3(fixedGravity_),
#endif
                measuredGravityBody);
            addGravityDirectionFactor(measuredGravityBody);
            addedGravityDirectionFactor = true;
        }
#endif
        // optimize
        optimizer.update(graphFactors, graphValues);
        optimizer.update();
        graphFactors.resize(0);
        graphValues.clear();
        // Overwrite the beginning of the preintegration for the next step.
        gtsam::Values result = optimizer.calculateEstimate();
        prevPose_  = result.at<gtsam::Pose3>(X(key));
        prevVel_   = result.at<gtsam::Vector3>(V(key));
        prevState_ = gtsam::NavState(prevPose_, prevVel_);
        updateBiasFromResult(result, B(key));
#if LIOSAM_ESTIMATE_GRAVITY
        prevGravity_ = result.at<gtsam::Unit3>(gravityKey());
#endif
#if LIOSAM_ENABLE_GRAVITY_DIRECTION
        if (addedGravityDirectionFactor)
        {
            const double postResidualDeg = gravityDirectionResidualDeg(
                prevPose_,
#if LIOSAM_ESTIMATE_GRAVITY
                prevGravity_,
#else
                gtsam::Unit3(fixedGravity_),
#endif
                measuredGravityBody);
            logGravityDirectionFactor(
                currentCorrectionTime, gravityDirectionMeasurementAge,
                gravityDirectionPreResidualDeg, postResidualDeg);
        }
#endif
        // Reset the optimization preintegration object.
        imuIntegratorOpt_->resetIntegrationAndSetBias(prevBias_);
        // check optimization
        if (failureDetection(prevVel_, prevBias_))
        {
            resetParams();
            return;
        }

        logOptimizedState(currentCorrectionTime);


        // 2. after optiization, re-propagate imu odometry preintegration
        prevStateOdom = prevState_;
        prevBiasOdom  = prevBias_;
        // first pop imu message older than current correction data
        double lastImuQT = -1;
        while (!imuQueImu.empty() && ROS_TIME(&imuQueImu.front()) < currentCorrectionTime - delta_t)
        {
            lastImuQT = ROS_TIME(&imuQueImu.front());
            imuQueImu.pop_front();
        }
        // repropogate
        if (!imuQueImu.empty())
        {
            // reset bias use the newly optimized bias
            imuIntegratorImu_->resetIntegrationAndSetBias(prevBiasOdom);
            // integrate imu message from the beginning of this optimization
            for (int i = 0; i < (int)imuQueImu.size(); ++i)
            {
                sensor_msgs::Imu *thisImu = &imuQueImu[i];
                double imuTime = ROS_TIME(thisImu);
                double dt = (lastImuQT < 0) ? (1.0 / 500.0) :(imuTime - lastImuQT);

                imuIntegratorImu_->integrateMeasurement(gtsam::Vector3(thisImu->linear_acceleration.x, thisImu->linear_acceleration.y, thisImu->linear_acceleration.z),
                                                        gtsam::Vector3(thisImu->angular_velocity.x,    thisImu->angular_velocity.y,    thisImu->angular_velocity.z), dt);
                lastImuQT = imuTime;
            }
        }

        ++key;
        doneFirstOpt = true;
    }

    bool failureDetection(const gtsam::Vector3& velCur, const gtsam::imuBias::ConstantBias& biasCur)
    {
        Eigen::Vector3f vel(velCur.x(), velCur.y(), velCur.z());
        if (vel.norm() > 30)
        {
            ROS_WARN("Large velocity, reset IMU-preintegration!");
            return true;
        }

        Eigen::Vector3f ba(biasCur.accelerometer().x(), biasCur.accelerometer().y(), biasCur.accelerometer().z());
        Eigen::Vector3f bg(biasCur.gyroscope().x(), biasCur.gyroscope().y(), biasCur.gyroscope().z());
        if (ba.norm() > 1.0 || bg.norm() > 1.0)
        {
            ROS_WARN("Large bias, reset IMU-preintegration!");
            return true;
        }

        return false;
    }

    void imuHandler(const sensor_msgs::Imu::ConstPtr& imu_raw)
    {
        std::lock_guard<std::mutex> lock(mtx);

        sensor_msgs::Imu thisImu = imuConverter(*imu_raw);

        imuQueOpt.push_back(thisImu);
        imuQueImu.push_back(thisImu);

        if (doneFirstOpt == false)
            return;

        double imuTime = ROS_TIME(&thisImu);
        double dt = (lastImuT_imu < 0) ? (1.0 / 500.0) : (imuTime - lastImuT_imu);
        lastImuT_imu = imuTime;

        // integrate this single imu message
        imuIntegratorImu_->integrateMeasurement(gtsam::Vector3(thisImu.linear_acceleration.x, thisImu.linear_acceleration.y, thisImu.linear_acceleration.z),
                                                gtsam::Vector3(thisImu.angular_velocity.x,    thisImu.angular_velocity.y,    thisImu.angular_velocity.z), dt);

        // predict odometry
        gtsam::NavState currentState = predictState(
            imuIntegratorImu_, prevStateOdom, prevBiasOdom);

        // publish odometry
        nav_msgs::Odometry odometry;
        odometry.header.stamp = thisImu.header.stamp;
        odometry.header.frame_id = odometryFrame;
        odometry.child_frame_id = "odom_imu";

        // transform imu pose to ldiar
        gtsam::Pose3 imuPose = gtsam::Pose3(currentState.quaternion(), currentState.position());
        gtsam::Pose3 lidarPose = imuPose.compose(imu2Lidar);

        odometry.pose.pose.position.x = lidarPose.translation().x();
        odometry.pose.pose.position.y = lidarPose.translation().y();
        odometry.pose.pose.position.z = lidarPose.translation().z();
        odometry.pose.pose.orientation.x = lidarPose.rotation().toQuaternion().x();
        odometry.pose.pose.orientation.y = lidarPose.rotation().toQuaternion().y();
        odometry.pose.pose.orientation.z = lidarPose.rotation().toQuaternion().z();
        odometry.pose.pose.orientation.w = lidarPose.rotation().toQuaternion().w();
        
        odometry.twist.twist.linear.x = currentState.velocity().x();
        odometry.twist.twist.linear.y = currentState.velocity().y();
        odometry.twist.twist.linear.z = currentState.velocity().z();
        odometry.twist.twist.angular.x = thisImu.angular_velocity.x + prevBiasOdom.gyroscope().x();
        odometry.twist.twist.angular.y = thisImu.angular_velocity.y + prevBiasOdom.gyroscope().y();
        odometry.twist.twist.angular.z = thisImu.angular_velocity.z + prevBiasOdom.gyroscope().z();
        pubImuOdometry.publish(odometry);
    }
};


int main(int argc, char** argv)
{
    ros::init(argc, argv, "roboat_loam");
    
    IMUPreintegration ImuP;

    TransformFusion TF;

    ROS_INFO("\033[1;32m----> IMU Preintegration Started.\033[0m");
    
    ros::MultiThreadedSpinner spinner(4);
    spinner.spin();
    
    return 0;
}

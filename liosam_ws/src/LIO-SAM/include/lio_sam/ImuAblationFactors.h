#pragma once

#include <gtsam/geometry/Unit3.h>
#include <gtsam/navigation/ImuFactor.h>
#include <gtsam/navigation/ImuFactorWithGravity.h>

namespace lio_sam_ablation {

/**
 * Standard fixed-gravity IMU factor with accelerometer bias removed from the
 * graph. The only bias variable is the 3-DOF gyroscope bias. Accelerometer
 * bias is an immutable constructor value; this is a true state reduction, not
 * a small-noise proxy.
 */
class ImuFactorFixedAccelBias final
    : public gtsam::NoiseModelFactorN<gtsam::Pose3, gtsam::Vector3,
                                      gtsam::Pose3, gtsam::Vector3,
                                      gtsam::Vector3> {
 private:
  using Base = gtsam::NoiseModelFactorN<gtsam::Pose3, gtsam::Vector3,
                                         gtsam::Pose3, gtsam::Vector3,
                                         gtsam::Vector3>;

  gtsam::PreintegratedImuMeasurements pim_;
  gtsam::Vector3 fixedAccelBias_;

 public:
  using Base::evaluateError;

  ImuFactorFixedAccelBias(
      gtsam::Key pose_i, gtsam::Key vel_i, gtsam::Key pose_j,
      gtsam::Key vel_j, gtsam::Key gyro_bias,
      const gtsam::PreintegratedImuMeasurements& pim,
      const gtsam::Vector3& fixed_accel_bias)
      : Base(gtsam::noiseModel::Gaussian::Covariance(
                 pim.residualCovariance()),
             pose_i, vel_i, pose_j, vel_j, gyro_bias),
        pim_(pim),
        fixedAccelBias_(fixed_accel_bias) {}

  gtsam::NonlinearFactor::shared_ptr clone() const override {
    return std::make_shared<ImuFactorFixedAccelBias>(*this);
  }

  gtsam::Vector evaluateError(
      const gtsam::Pose3& pose_i, const gtsam::Vector3& vel_i,
      const gtsam::Pose3& pose_j, const gtsam::Vector3& vel_j,
      const gtsam::Vector3& gyro_bias, gtsam::OptionalMatrixType H1,
      gtsam::OptionalMatrixType H2, gtsam::OptionalMatrixType H3,
      gtsam::OptionalMatrixType H4,
      gtsam::OptionalMatrixType H5) const override {
    const gtsam::imuBias::ConstantBias full_bias(fixedAccelBias_, gyro_bias);
    const gtsam::ImuFactor delegate(0, 1, 2, 3, 4, pim_);
    gtsam::Matrix H_full_bias;
    const gtsam::Vector error = delegate.evaluateError(
        pose_i, vel_i, pose_j, vel_j, full_bias, H1, H2, H3, H4,
        H5 ? &H_full_bias : nullptr);
    if (H5) {
      *H5 = H_full_bias.rightCols<3>();
    }
    return error;
  }
};

/**
 * Gravity-direction IMU factor with accelerometer bias removed from the graph.
 * Gravity is a shared 2-DOF Unit3 variable and its magnitude is fixed.
 */
class ImuFactorWithGravityFixedAccelBias final
    : public gtsam::NoiseModelFactorN<gtsam::Pose3, gtsam::Vector3,
                                      gtsam::Pose3, gtsam::Vector3,
                                      gtsam::Vector3, gtsam::Unit3> {
 private:
  using Base = gtsam::NoiseModelFactorN<gtsam::Pose3, gtsam::Vector3,
                                         gtsam::Pose3, gtsam::Vector3,
                                         gtsam::Vector3, gtsam::Unit3>;

  gtsam::PreintegratedImuMeasurements pim_;
  gtsam::Vector3 fixedAccelBias_;
  double gravityMagnitude_;

 public:
  using Base::evaluateError;

  ImuFactorWithGravityFixedAccelBias(
      gtsam::Key pose_i, gtsam::Key vel_i, gtsam::Key pose_j,
      gtsam::Key vel_j, gtsam::Key gyro_bias, gtsam::Key gravity,
      const gtsam::PreintegratedImuMeasurements& pim,
      const gtsam::Vector3& fixed_accel_bias, double gravity_magnitude)
      : Base(gtsam::noiseModel::Gaussian::Covariance(
                 pim.residualCovariance()),
             pose_i, vel_i, pose_j, vel_j, gyro_bias, gravity),
        pim_(pim),
        fixedAccelBias_(fixed_accel_bias),
        gravityMagnitude_(gravity_magnitude) {}

  gtsam::NonlinearFactor::shared_ptr clone() const override {
    return std::make_shared<ImuFactorWithGravityFixedAccelBias>(*this);
  }

  gtsam::Vector evaluateError(
      const gtsam::Pose3& pose_i, const gtsam::Vector3& vel_i,
      const gtsam::Pose3& pose_j, const gtsam::Vector3& vel_j,
      const gtsam::Vector3& gyro_bias, const gtsam::Unit3& gravity,
      gtsam::OptionalMatrixType H1, gtsam::OptionalMatrixType H2,
      gtsam::OptionalMatrixType H3, gtsam::OptionalMatrixType H4,
      gtsam::OptionalMatrixType H5,
      gtsam::OptionalMatrixType H6) const override {
    const gtsam::imuBias::ConstantBias full_bias(fixedAccelBias_, gyro_bias);
    const gtsam::ImuFactorWithGravityDirection delegate(
        0, 1, 2, 3, 4, 5, pim_, gravityMagnitude_);
    gtsam::Matrix H_full_bias;
    const gtsam::Vector error = delegate.evaluateError(
        pose_i, vel_i, pose_j, vel_j, full_bias, gravity, H1, H2, H3, H4,
        H5 ? &H_full_bias : nullptr, H6);
    if (H5) {
      *H5 = H_full_bias.rightCols<3>();
    }
    return error;
  }
};

/**
 * A two-dimensional gravity-direction observation for a fixed world gravity.
 * The measured Unit3 lives in the IMU/body frame. Translation and yaw about
 * gravity are intentionally unobserved.
 */
class GravityDirectionFactorFixed final
    : public gtsam::NoiseModelFactor1<gtsam::Pose3> {
 private:
  using Base = gtsam::NoiseModelFactor1<gtsam::Pose3>;

  gtsam::Unit3 gravityWorld_;
  gtsam::Unit3 measuredGravityBody_;

 public:
  using Base::evaluateError;

  GravityDirectionFactorFixed(
      gtsam::Key pose, const gtsam::Unit3& gravity_world,
      const gtsam::Unit3& measured_gravity_body,
      const gtsam::SharedNoiseModel& noise)
      : Base(noise, pose),
        gravityWorld_(gravity_world),
        measuredGravityBody_(measured_gravity_body) {}

  gtsam::NonlinearFactor::shared_ptr clone() const override {
    return std::make_shared<GravityDirectionFactorFixed>(*this);
  }

  gtsam::Vector evaluateError(
      const gtsam::Pose3& pose,
      gtsam::OptionalMatrixType H_pose) const override {
    gtsam::Matrix23 H_predicted_rotation;
    const gtsam::Unit3 predicted_body = pose.rotation().unrotate(
        gravityWorld_, H_pose ? &H_predicted_rotation : nullptr);

    gtsam::Matrix22 H_error_predicted;
    const gtsam::Vector2 error = measuredGravityBody_.errorVector(
        predicted_body, {}, H_pose ? &H_error_predicted : nullptr);
    if (H_pose) {
      *H_pose = gtsam::Matrix::Zero(2, 6);
      H_pose->leftCols<3>() = H_error_predicted * H_predicted_rotation;
    }
    return error;
  }
};

/**
 * The same two-dimensional observation when gravity direction is a shared
 * Unit3 graph variable. Its magnitude remains fixed by the IMU model.
 */
class GravityDirectionFactorEstimated final
    : public gtsam::NoiseModelFactor2<gtsam::Pose3, gtsam::Unit3> {
 private:
  using Base = gtsam::NoiseModelFactor2<gtsam::Pose3, gtsam::Unit3>;

  gtsam::Unit3 measuredGravityBody_;

 public:
  using Base::evaluateError;

  GravityDirectionFactorEstimated(
      gtsam::Key pose, gtsam::Key gravity,
      const gtsam::Unit3& measured_gravity_body,
      const gtsam::SharedNoiseModel& noise)
      : Base(noise, pose, gravity),
        measuredGravityBody_(measured_gravity_body) {}

  gtsam::NonlinearFactor::shared_ptr clone() const override {
    return std::make_shared<GravityDirectionFactorEstimated>(*this);
  }

  gtsam::Vector evaluateError(
      const gtsam::Pose3& pose, const gtsam::Unit3& gravity_world,
      gtsam::OptionalMatrixType H_pose,
      gtsam::OptionalMatrixType H_gravity) const override {
    gtsam::Matrix23 H_predicted_rotation;
    gtsam::Matrix22 H_predicted_gravity;
    const gtsam::Unit3 predicted_body = pose.rotation().unrotate(
        gravity_world, H_pose ? &H_predicted_rotation : nullptr,
        H_gravity ? &H_predicted_gravity : nullptr);

    gtsam::Matrix22 H_error_predicted;
    const gtsam::Vector2 error = measuredGravityBody_.errorVector(
        predicted_body, {}, (H_pose || H_gravity) ? &H_error_predicted
                                                  : nullptr);
    if (H_pose) {
      *H_pose = gtsam::Matrix::Zero(2, 6);
      H_pose->leftCols<3>() = H_error_predicted * H_predicted_rotation;
    }
    if (H_gravity) {
      *H_gravity = H_error_predicted * H_predicted_gravity;
    }
    return error;
  }
};

}  // namespace lio_sam_ablation

#include <cmath>
#include <iostream>

#include <gtsam/navigation/ImuFactor.h>
#include <gtsam/navigation/ImuFactorWithGravity.h>
#include <gtsam/base/numericalDerivative.h>

#include "lio_sam/ImuAblationFactors.h"

namespace {

bool near(const gtsam::Matrix& actual, const gtsam::Matrix& expected,
          double tolerance, const char* label) {
  const double error = (actual - expected).cwiseAbs().maxCoeff();
  if (error > tolerance || !std::isfinite(error)) {
    std::cerr << label << " max error = " << error << '\n';
    return false;
  }
  return true;
}

}  // namespace

int main() {
  constexpr double kGravity = 9.805;
  auto params = gtsam::PreintegrationParams::MakeSharedU(kGravity);
  params->accelerometerCovariance = gtsam::Matrix33::Identity() * 1e-4;
  params->gyroscopeCovariance = gtsam::Matrix33::Identity() * 1e-5;
  params->integrationCovariance = gtsam::Matrix33::Identity() * 1e-8;

  const gtsam::Vector3 fixed_ba(0.03, -0.02, 0.01);
  const gtsam::Vector3 bg(0.002, -0.003, 0.001);
  const gtsam::imuBias::ConstantBias full_bias(fixed_ba, bg);
  gtsam::PreintegratedImuMeasurements pim(params, full_bias);
  for (int i = 0; i < 20; ++i) {
    pim.integrateMeasurement(gtsam::Vector3(0.2, -0.1, -9.6),
                             gtsam::Vector3(0.01, 0.02, -0.015), 0.01);
  }

  const gtsam::Pose3 pose_i(gtsam::Rot3::RzRyRx(0.03, -0.04, 0.1),
                            gtsam::Point3(1.0, -2.0, 0.3));
  const gtsam::Pose3 pose_j(gtsam::Rot3::RzRyRx(0.035, -0.036, 0.103),
                            gtsam::Point3(1.1, -1.98, 0.31));
  const gtsam::Vector3 vel_i(0.5, 0.1, -0.02);
  const gtsam::Vector3 vel_j(0.51, 0.09, -0.01);
  const gtsam::Unit3 gravity(params->n_gravity);

  const gtsam::ImuFactor standard_fixed_g(0, 1, 2, 3, 4, pim);
  const lio_sam_ablation::ImuFactorFixedAccelBias reduced_fixed_g(
      0, 1, 2, 3, 4, pim, fixed_ba);

  gtsam::Matrix s1, s2, s3, s4, sb;
  gtsam::Matrix r1, r2, r3, r4, rbg;
  const gtsam::Vector standard_error = standard_fixed_g.evaluateError(
      pose_i, vel_i, pose_j, vel_j, full_bias, &s1, &s2, &s3, &s4, &sb);
  const gtsam::Vector reduced_error = reduced_fixed_g.evaluateError(
      pose_i, vel_i, pose_j, vel_j, bg, &r1, &r2, &r3, &r4, &rbg);

  bool ok = near(reduced_error, standard_error, 1e-12, "FG error") &&
            near(r1, s1, 1e-12, "FG H1") &&
            near(r2, s2, 1e-12, "FG H2") &&
            near(r3, s3, 1e-12, "FG H3") &&
            near(r4, s4, 1e-12, "FG H4") &&
            near(rbg, sb.rightCols<3>(), 1e-12, "FG Hbg");

  const gtsam::ImuFactorWithGravityDirection standard_gravity(
      0, 1, 2, 3, 4, 5, pim, kGravity);
  const lio_sam_ablation::ImuFactorWithGravityFixedAccelBias reduced_gravity(
      0, 1, 2, 3, 4, 5, pim, fixed_ba, kGravity);

  gtsam::Matrix gs1, gs2, gs3, gs4, gsb, gsg;
  gtsam::Matrix gr1, gr2, gr3, gr4, grbg, grg;
  const gtsam::Vector standard_gravity_error =
      standard_gravity.evaluateError(pose_i, vel_i, pose_j, vel_j, full_bias,
                                     gravity, &gs1, &gs2, &gs3, &gs4, &gsb,
                                     &gsg);
  const gtsam::Vector reduced_gravity_error =
      reduced_gravity.evaluateError(pose_i, vel_i, pose_j, vel_j, bg, gravity,
                                    &gr1, &gr2, &gr3, &gr4, &grbg, &grg);

  ok = near(reduced_gravity_error, standard_gravity_error, 1e-12,
            "GE error") &&
       near(gr1, gs1, 1e-12, "GE H1") &&
       near(gr2, gs2, 1e-12, "GE H2") &&
       near(gr3, gs3, 1e-12, "GE H3") &&
       near(gr4, gs4, 1e-12, "GE H4") &&
       near(grbg, gsb.rightCols<3>(), 1e-12, "GE Hbg") &&
       near(grg, gsg, 1e-12, "GE Hg") && ok;

  const auto direction_noise = gtsam::noiseModel::Isotropic::Sigma(2, 0.05);
  const gtsam::Pose3 direction_pose(
      gtsam::Rot3::RzRyRx(0.08, -0.06, 0.7), gtsam::Point3(4.0, -3.0, 2.0));
  const gtsam::Unit3 gravity_world(gtsam::Vector3(0.0, 0.0, -1.0));
  const gtsam::Unit3 measured_body =
      direction_pose.rotation().unrotate(gravity_world);

  const lio_sam_ablation::GravityDirectionFactorFixed fixed_direction(
      0, gravity_world, measured_body, direction_noise);
  gtsam::Matrix fixed_H;
  const gtsam::Vector fixed_error =
      fixed_direction.evaluateError(direction_pose, &fixed_H);
  const gtsam::Matrix fixed_H_numerical =
      gtsam::numericalDerivative11<gtsam::Vector, gtsam::Pose3>(
          [&fixed_direction](const gtsam::Pose3& p) {
            return fixed_direction.evaluateError(p);
          },
          direction_pose);
  ok = near(fixed_error, gtsam::Vector2::Zero(), 1e-12,
            "direction fixed zero error") &&
       near(fixed_H, fixed_H_numerical, 1e-7,
            "direction fixed Jacobian") && ok;

  const gtsam::Pose3 yaw_only(
      gtsam::Rot3::Rz(0.4).compose(direction_pose.rotation()),
      direction_pose.translation());
  const double yaw_error = fixed_direction.evaluateError(yaw_only).norm();
  if (yaw_error > 1e-10) {
    std::cerr << "gravity direction unexpectedly observes world yaw: "
              << yaw_error << '\n';
    ok = false;
  }

  const gtsam::Pose3 roll_perturbed(
      direction_pose.rotation().compose(gtsam::Rot3::Rx(0.1)),
      direction_pose.translation());
  const double roll_error = fixed_direction.evaluateError(roll_perturbed).norm();
  if (roll_error < 0.05) {
    std::cerr << "gravity direction failed to observe tilt: " << roll_error
              << '\n';
    ok = false;
  }

  const lio_sam_ablation::GravityDirectionFactorEstimated estimated_direction(
      0, 1, measured_body, direction_noise);
  gtsam::Matrix estimated_H_pose, estimated_H_gravity;
  const gtsam::Vector estimated_error = estimated_direction.evaluateError(
      direction_pose, gravity_world, &estimated_H_pose, &estimated_H_gravity);
  const auto estimated_function =
      [&estimated_direction](const gtsam::Pose3& p, const gtsam::Unit3& g) {
        return estimated_direction.evaluateError(p, g);
      };
  const gtsam::Matrix estimated_H_pose_numerical =
      gtsam::numericalDerivative21<gtsam::Vector, gtsam::Pose3, gtsam::Unit3>(
          estimated_function, direction_pose, gravity_world);
  const gtsam::Matrix estimated_H_gravity_numerical =
      gtsam::numericalDerivative22<gtsam::Vector, gtsam::Pose3, gtsam::Unit3>(
          estimated_function, direction_pose, gravity_world);
  ok = near(estimated_error, fixed_error, 1e-12,
            "direction FG/GE error") &&
       near(estimated_H_pose, estimated_H_pose_numerical, 1e-7,
            "direction GE pose Jacobian") &&
       near(estimated_H_gravity, estimated_H_gravity_numerical, 1e-7,
            "direction GE gravity Jacobian") && ok;

  if (!ok) return 1;
  std::cout << "IMU ablation and gravity-direction factors passed\n";
  return 0;
}

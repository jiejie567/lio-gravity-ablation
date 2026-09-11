cmake_minimum_required(VERSION 2.8.3)
project(lio_sam)

set(CMAKE_BUILD_TYPE "Release")
set(CMAKE_CXX_FLAGS "-std=c++17 -DUSE_UNORDERED_MAP=0")
set(CMAKE_CXX_FLAGS_RELEASE "-O3 -Wall -g -pthread")

find_package(catkin REQUIRED COMPONENTS
  tf
  roscpp
  rospy
  cv_bridge
  # pcl library
  pcl_conversions
  # msgs
  std_msgs
  sensor_msgs
  geometry_msgs
  nav_msgs
  message_generation
  visualization_msgs
)

find_package(OpenMP REQUIRED)
find_package(PCL REQUIRED QUIET)
find_package(OpenCV REQUIRED QUIET)
find_package(GTSAM REQUIRED QUIET)
find_package(Boost REQUIRED COMPONENTS timer)

add_message_files(
  DIRECTORY msg
  FILES
  cloud_info.msg
)

add_service_files(
  DIRECTORY srv
  FILES
  save_map.srv
)

generate_messages(
  DEPENDENCIES
  geometry_msgs
  std_msgs
  nav_msgs
  sensor_msgs
)

catkin_package(
  INCLUDE_DIRS include
  DEPENDS PCL GTSAM

  CATKIN_DEPENDS
  std_msgs
  nav_msgs
  geometry_msgs
  sensor_msgs
  message_runtime
  message_generation
  visualization_msgs
)

# include directories
include_directories(BEFORE
	${GTSAM_INCLUDE_DIR}/gtsam/3rdparty/Eigen
	)

include_directories(
	include
	${catkin_INCLUDE_DIRS}
	${PCL_INCLUDE_DIRS}
  ${OpenCV_INCLUDE_DIRS}
	${GTSAM_INCLUDE_DIR}
)

# link directories
link_directories(
	include
	${PCL_LIBRARY_DIRS}
  ${OpenCV_LIBRARY_DIRS}
  ${GTSAM_LIBRARY_DIRS}
)

###########
## Build ##
###########

# Range Image Projection
add_executable(${PROJECT_NAME}_imageProjection src/imageProjection.cpp)
add_dependencies(${PROJECT_NAME}_imageProjection ${catkin_EXPORTED_TARGETS} ${PROJECT_NAME}_generate_messages_cpp)
target_link_libraries(${PROJECT_NAME}_imageProjection ${catkin_LIBRARIES} ${PCL_LIBRARIES} ${OpenCV_LIBRARIES})

# Feature Association
add_executable(${PROJECT_NAME}_featureExtraction src/featureExtraction.cpp)
add_dependencies(${PROJECT_NAME}_featureExtraction ${catkin_EXPORTED_TARGETS} ${PROJECT_NAME}_generate_messages_cpp)
target_link_libraries(${PROJECT_NAME}_featureExtraction ${catkin_LIBRARIES} ${PCL_LIBRARIES} ${OpenCV_LIBRARIES})

# Mapping Optimization
add_executable(${PROJECT_NAME}_mapOptmization src/mapOptmization.cpp)
add_dependencies(${PROJECT_NAME}_mapOptmization ${catkin_EXPORTED_TARGETS} ${PROJECT_NAME}_generate_messages_cpp)
target_compile_options(${PROJECT_NAME}_mapOptmization PRIVATE ${OpenMP_CXX_FLAGS})
target_link_libraries(${PROJECT_NAME}_mapOptmization Boost::timer ${catkin_LIBRARIES} ${PCL_LIBRARIES} ${OpenCV_LIBRARIES} ${OpenMP_CXX_FLAGS} gtsam)

# IMU Preintegration
add_executable(${PROJECT_NAME}_imuPreintegration src/imuPreintegration.cpp)
target_compile_definitions(${PROJECT_NAME}_imuPreintegration PRIVATE
  LIOSAM_ESTIMATE_GRAVITY=0 LIOSAM_ESTIMATE_ACCEL_BIAS=1
  LIOSAM_ENABLE_GRAVITY_DIRECTION=0)
target_link_libraries(${PROJECT_NAME}_imuPreintegration Boost::timer ${catkin_LIBRARIES} ${PCL_LIBRARIES} ${OpenCV_LIBRARIES} gtsam)

function(add_imu_ablation_variant suffix estimate_gravity estimate_accel_bias)
  set(target ${PROJECT_NAME}_imuPreintegration_${suffix})
  add_executable(${target} src/imuPreintegration.cpp)
  target_compile_definitions(${target} PRIVATE
    LIOSAM_ESTIMATE_GRAVITY=${estimate_gravity}
    LIOSAM_ESTIMATE_ACCEL_BIAS=${estimate_accel_bias}
    LIOSAM_ENABLE_GRAVITY_DIRECTION=0)
  target_link_libraries(${target} Boost::timer ${catkin_LIBRARIES}
    ${PCL_LIBRARIES} ${OpenCV_LIBRARIES} gtsam)
endfunction()

add_imu_ablation_variant(fg_b0 0 0)
add_imu_ablation_variant(ge_ba 1 1)
add_imu_ablation_variant(ge_b0 1 0)

function(add_gravity_direction_variant suffix estimate_gravity)
  set(target ${PROJECT_NAME}_imuPreintegration_${suffix}_gdir)
  add_executable(${target} src/imuPreintegration.cpp)
  target_compile_definitions(${target} PRIVATE
    LIOSAM_ESTIMATE_GRAVITY=${estimate_gravity}
    LIOSAM_ESTIMATE_ACCEL_BIAS=1
    LIOSAM_ENABLE_GRAVITY_DIRECTION=1)
  target_link_libraries(${target} Boost::timer ${catkin_LIBRARIES}
    ${PCL_LIBRARIES} ${OpenCV_LIBRARIES} gtsam)
endfunction()

add_gravity_direction_variant(fg_ba 0)
add_gravity_direction_variant(ge_ba 1)

add_executable(${PROJECT_NAME}_test_imu_ablation_factors
  test/test_imu_ablation_factors.cpp)
target_link_libraries(${PROJECT_NAME}_test_imu_ablation_factors gtsam)

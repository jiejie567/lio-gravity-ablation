cmake_minimum_required(VERSION 2.8.3)
project(fast_lio)

SET(CMAKE_BUILD_TYPE "Debug")

ADD_COMPILE_OPTIONS(-std=c++14 )
ADD_COMPILE_OPTIONS(-std=c++14 )
set( CMAKE_CXX_FLAGS "-std=c++14 -O3" )

add_definitions(-DROOT_DIR=\"${CMAKE_CURRENT_SOURCE_DIR}/\")

set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -fexceptions" )
set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -std=c++14 -pthread -std=c++0x -std=c++14 -fexceptions")

message("Current CPU archtecture: ${CMAKE_SYSTEM_PROCESSOR}")
if(CMAKE_SYSTEM_PROCESSOR MATCHES "(x86)|(X86)|(amd64)|(AMD64)" )
  include(ProcessorCount)
  ProcessorCount(N)
  message("Processer number:  ${N}")
  if(N GREATER 4)
    add_definitions(-DMP_EN)
    add_definitions(-DMP_PROC_NUM=3)
    message("core for MP: 3")
  elseif(N GREATER 3)
    add_definitions(-DMP_EN)
    add_definitions(-DMP_PROC_NUM=2)
    message("core for MP: 2")
  else()
    add_definitions(-DMP_PROC_NUM=1)
  endif()
else()
  add_definitions(-DMP_PROC_NUM=1)
endif()

find_package(OpenMP QUIET)
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} ${OpenMP_CXX_FLAGS}")
set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS}   ${OpenMP_C_FLAGS}")

find_package(PythonLibs REQUIRED)
find_path(MATPLOTLIB_CPP_INCLUDE_DIRS "matplotlibcpp.h")

find_package(catkin REQUIRED COMPONENTS
  geometry_msgs
  nav_msgs
  sensor_msgs
  roscpp
  rospy
  std_msgs
  pcl_ros
  tf
  livox_ros_driver
  message_generation
  eigen_conversions
)

find_package(Eigen3 REQUIRED)
find_package(PCL 1.8 REQUIRED)

message(Eigen: ${EIGEN3_INCLUDE_DIR})

include_directories(
	${catkin_INCLUDE_DIRS} 
  ${EIGEN3_INCLUDE_DIR}
  ${PCL_INCLUDE_DIRS}
  ${PYTHON_INCLUDE_DIRS}
  include)

add_message_files(
  FILES
  Pose6D.msg
)

generate_messages(
 DEPENDENCIES
 geometry_msgs
)

catkin_package(
  CATKIN_DEPENDS geometry_msgs nav_msgs roscpp rospy std_msgs message_runtime
  DEPENDS EIGEN3 PCL
  INCLUDE_DIRS
)

add_executable(fastlio_mapping src/laserMapping.cpp include/ikd-Tree/ikd_Tree.cpp src/preprocess.cpp)
target_link_libraries(fastlio_mapping ${catkin_LIBRARIES} ${PCL_LIBRARIES} ${PYTHON_LIBRARIES})

# [reduced-18] 真降维变体: 把 ba(3) 与 grav(2) 移出状态向量 → 误差状态 23→18。
# 用途: 检验"dx 清零冻结"与"真正不估计"是否等价(前者保留了这两块的协方差)。
add_executable(fastlio_mapping_red src/laserMapping_red.cpp include/ikd-Tree/ikd_Tree.cpp src/preprocess.cpp)
target_link_libraries(fastlio_mapping_red ${catkin_LIBRARIES} ${PCL_LIBRARIES} ${PYTHON_LIBRARIES})
target_include_directories(fastlio_mapping_red PRIVATE ${PYTHON_INCLUDE_DIRS})

# [reduced-21] 只把 grav(2) 移出状态,ba 仍在线估计 → 23→21。策略 B 的真实现。
add_executable(fastlio_mapping_redg src/laserMapping_redg.cpp include/ikd-Tree/ikd_Tree.cpp src/preprocess.cpp)
target_link_libraries(fastlio_mapping_redg ${catkin_LIBRARIES} ${PCL_LIBRARIES} ${PYTHON_LIBRARIES})
target_include_directories(fastlio_mapping_redg PRIVATE ${PYTHON_INCLUDE_DIRS})

# [reduced-20] 只把 ba(3) 移出状态,重力仍在线估计 → 23→20。策略 D 的真实现。
# 注意 ba 在 grav 之前,移除后 grav 的误差状态索引由 21 前移到 18。
add_executable(fastlio_mapping_redb src/laserMapping_redb.cpp include/ikd-Tree/ikd_Tree.cpp src/preprocess.cpp)
target_link_libraries(fastlio_mapping_redb ${catkin_LIBRARIES} ${PCL_LIBRARIES} ${PYTHON_LIBRARIES})
target_include_directories(fastlio_mapping_redb PRIVATE ${PYTHON_INCLUDE_DIRS})
target_include_directories(fastlio_mapping PRIVATE ${PYTHON_INCLUDE_DIRS})
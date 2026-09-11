# FAST-LIO2 Frozen Gravity 实验环境 (arm64 native on Apple Silicon)
FROM ros:noetic

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake git wget curl unzip \
    libeigen3-dev libpcl-dev \
    ros-noetic-pcl-ros ros-noetic-pcl-conversions ros-noetic-eigen-conversions \
    ros-noetic-tf ros-noetic-rosbag \
    python3-pip python3-dev python3-matplotlib \
    && rm -rf /var/lib/apt/lists/*

# 分析用 Python 库(容器内跑 analyze.py,宿主机保持干净)
# --upgrade 让 pip 的新 numpy 覆盖 apt 自带的旧版,否则 pandas 导入报错
RUN pip3 install --no-cache-dir --upgrade numpy pandas scipy

# Livox-SDK (livox_ros_driver 依赖)
RUN git clone --depth 1 https://github.com/Livox-SDK/Livox-SDK.git /opt/Livox-SDK \
    && cd /opt/Livox-SDK/build && cmake .. && make -j$(nproc) && make install \
    && rm -rf /opt/Livox-SDK

# 容器内工作目录 = 挂载进来的项目根
WORKDIR /work
RUN echo 'source /opt/ros/noetic/setup.bash' >> /root/.bashrc \
    && echo '[ -f /work/catkin_ws/devel/setup.bash ] && source /work/catkin_ws/devel/setup.bash' >> /root/.bashrc

CMD ["bash"]

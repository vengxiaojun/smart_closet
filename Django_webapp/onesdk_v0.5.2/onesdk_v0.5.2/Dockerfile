FROM hub.byted.org/codebase/ci_debian_bullseye:latest

# 安装基础编译工具链
RUN apt-get update && apt-get install -y \
    build-essential \
    gcc \
    g++ \
    make \
    cmake \
    lcov \
    git \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*
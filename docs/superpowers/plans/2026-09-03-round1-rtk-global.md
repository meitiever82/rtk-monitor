# 轮 1:gnss_msgs + gnss_core + rtk_global 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付质量感知的 GNSS 全局约束模块 `rtk_global`,连同其纯 C++ 算法核心 `gnss_core`、统一消息包 `gnss_msgs`、驱动增发的 `RtkFix` topic,以及无 LiDAR 的轨迹对比与定权系数标定工具。

**Architecture:** 纯 C++17 算法核心 `gnss_core`(无 ROS、无 GLIM 依赖,依赖 Eigen/GTSAM/GeographicLib),被三个薄壳复用。本轮只做 `rtk_global`(GLIM extension module 壳)与轨迹对比工具。算法单元(噪声策略、fix 缓冲、帧对齐、带杆臂因子)全部可脱离 ROS/GLIM 单测。

**Tech Stack:** C++17、CMake、ament_cmake、Eigen3、GTSAM 4.3、gtsam_points、GeographicLib 2.3、GLIM extension module API、GoogleTest、ROS2 Jazzy。

**Spec:** `rtk-monitor/docs/superpowers/specs/2026-09-03-gnss-glim-modules-design.md`

## Global Constraints

- `gnss_core` 严禁依赖 ROS 与 GLIM;仅允许 Eigen / GTSAM / GeographicLib(spec §6)。
- 算法只写一遍在 `gnss_core`,壳只做订阅、类型转换、回调注册(spec §2.1)。
- 坐标换算一律用 `GeographicLib::LocalCartesian`,不自写第四份 geodetic;局部 ENU 而非 UTM(spec §6.1)。
- `RtkFix` 质量枚举归一化、源无关:`QUALITY_NONE=0 SINGLE=1 DGPS=2 FLOAT=3 FIXED=4`(spec §4.1)。
- GTSAM 4.3;自定义因子须过 `gtsam::numericalDerivative11` 的 Jacobian 数值校验(spec §12.1)。
- `rtk_global` 与 `gnss_global` 互斥,不得同时启用(spec §7.6)。
- 目标平台 aarch64(Orin);系统已装 GTSAM 4.3(`/usr/local/include/gtsam`)、GeographicLib 2.3(`/usr/share/cmake/geographiclib/FindGeographicLib.cmake`)。
- 每个任务 TDD:先写失败测试 → 跑失败 → 最小实现 → 跑通过 → 提交。

---

## 文件结构

**新建包 `gnss_msgs`**(ROS2 消息,独立包):
- `gnss_msgs/msg/RtkFix.msg` — 带质量标签的 GNSS 定位
- `gnss_msgs/msg/RawStream.msg` — 裸字节流
- `gnss_msgs/CMakeLists.txt` / `package.xml`

**新建包 `gnss_core`**(纯 C++ 库,ament_cmake,导出为库供壳链接):
- `include/gnss_core/types.hpp` — `Quality` 枚举、`RtkFixSample`、`EnuPoint`
- `include/gnss_core/geodetic.hpp` + `src/geodetic.cpp` — `LlaToEnu`(封装 GeographicLib::LocalCartesian)
- `include/gnss_core/rtk_fix_buffer.hpp` + `src/rtk_fix_buffer.cpp` — 时间插值缓冲
- `include/gnss_core/rtk_noise_policy.hpp` + `src/rtk_noise_policy.cpp` — 质量→noise model / 拒绝
- `include/gnss_core/frame_aligner.hpp` + `src/frame_aligner.cpp` — SVD 求 `T_world_enu`
- `include/gnss_core/antenna_prior_factor.hpp` — GTSAM 自定义因子(header-only)
- `include/gnss_core/trajectory_compare.hpp` + `src/trajectory_compare.cpp` — 分档误差统计
- `include/gnss_core/pos_io.hpp` + `src/pos_io.cpp` — `.pos` 读取
- `test/` — 每单元一个 gtest

**新建模块 `glim_ext/modules/mapping/rtk_global`**:
- `include/glim_ext/rtk_global_module.hpp` — `ExtensionModuleROS2` 子类
- `src/glim_ext/rtk_global_module_ros2.cpp` — 接线 + `create_extension_module()`
- `CMakeLists.txt` / `package.xml`

**新建配置**:`glim_ext/config/config_rtk_global.json`

**修改驱动**:`driver_ws/src/gnss_CGI610`(增发 `~/rtk_fix`)

**新建工具**:`gnss_core/tools/calibrate_sigma_scale.cpp`(读多个 `.pos` → 分档统计 → 打印标定表)

---

### Task 1: gnss_msgs 消息包

**Files:**
- Create: `driver_ws/src/gnss_msgs/msg/RtkFix.msg`
- Create: `driver_ws/src/gnss_msgs/msg/RawStream.msg`
- Create: `driver_ws/src/gnss_msgs/CMakeLists.txt`
- Create: `driver_ws/src/gnss_msgs/package.xml`

**Interfaces:**
- Produces: `gnss_msgs/msg/RtkFix`(字段见下)、`gnss_msgs/msg/RawStream`。供 Task 8(驱动)、Task 9(模块壳)使用。

- [ ] **Step 1: 写 RtkFix.msg**

```
# gnss_msgs/RtkFix.msg —— 带质量标签的 GNSS 定位
std_msgs/Header header

uint8 QUALITY_NONE=0
uint8 QUALITY_SINGLE=1
uint8 QUALITY_DGPS=2
uint8 QUALITY_FLOAT=3
uint8 QUALITY_FIXED=4
uint8 quality
uint8 raw_status

float64 latitude
float64 longitude
float64 altitude
float64[3] sigma_enu

float32 diff_age
uint8 sats_used
uint8 sats_main
uint8 sats_aux

float32 heading
float32 heading_sigma
bool heading_valid
```

- [ ] **Step 2: 写 RawStream.msg**

```
# gnss_msgs/RawStream.msg —— 裸字节流(差分/原始观测通用)
std_msgs/Header header
uint8[] data
```

- [ ] **Step 3: 写 package.xml**

```xml
<?xml version="1.0"?>
<package format="3">
  <name>gnss_msgs</name>
  <version>0.1.0</version>
  <description>GNSS messages with quality labels for the GLIM ecosystem</description>
  <maintainer email="dev@example.com">dev</maintainer>
  <license>Apache-2.0</license>

  <buildtool_depend>ament_cmake</buildtool_depend>
  <buildtool_depend>rosidl_default_generators</buildtool_depend>
  <depend>std_msgs</depend>
  <exec_depend>rosidl_default_runtime</exec_depend>
  <member_of_group>rosidl_interface_packages</member_of_group>

  <export>
    <build_type>ament_cmake</build_type>
  </export>
</package>
```

- [ ] **Step 4: 写 CMakeLists.txt**

```cmake
cmake_minimum_required(VERSION 3.8)
project(gnss_msgs)

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(std_msgs REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/RtkFix.msg"
  "msg/RawStream.msg"
  DEPENDENCIES std_msgs
)

ament_package()
```

- [ ] **Step 5: 构建验证**

Run: `cd /home/steve/driver_ws && colcon build --packages-select gnss_msgs`
Expected: 构建成功,生成 `gnss_msgs/msg/RtkFix` 类型。

- [ ] **Step 6: 类型可见性验证**

Run: `cd /home/steve/driver_ws && source install/setup.bash && ros2 interface show gnss_msgs/msg/RtkFix`
Expected: 打印完整字段定义,含 `QUALITY_FIXED=4` 常量。

- [ ] **Step 7: Commit**

```bash
cd /home/steve/driver_ws && git add src/gnss_msgs && \
git commit -m "feat(gnss_msgs): RtkFix and RawStream messages"
```

---

### Task 2: gnss_core 包骨架 + types

**Files:**
- Create: `gnss_core/CMakeLists.txt`
- Create: `gnss_core/package.xml`
- Create: `gnss_core/include/gnss_core/types.hpp`
- Test: `gnss_core/test/test_types.cpp`

**Interfaces:**
- Produces: `gnss_core::Quality`(enum: `NONE=0,SINGLE=1,DGPS=2,FLOAT=3,FIXED=4`)、`struct RtkFixSample`、`struct EnuPoint`。所有后续 Task 消费。

- [ ] **Step 1: 写 types.hpp**

```cpp
#pragma once
#include <cstdint>
#include <Eigen/Core>

namespace gnss_core {

enum class Quality : uint8_t { NONE = 0, SINGLE = 1, DGPS = 2, FLOAT = 3, FIXED = 4 };

// 源无关的一条 GNSS 定位样本(与 gnss_msgs/RtkFix 对应,但不依赖 ROS 类型)
struct RtkFixSample {
  double stamp = 0.0;            // unix seconds
  Quality quality = Quality::NONE;
  double lat = 0.0, lon = 0.0, alt = 0.0;   // WGS-84, deg/deg/m
  Eigen::Vector3d sigma_enu = Eigen::Vector3d::Zero();  // m
  double diff_age = 0.0;         // s
  int sats_used = 0;
  double heading = 0.0;          // deg
  bool heading_valid = false;
};

struct EnuPoint {
  double stamp = 0.0;
  Eigen::Vector3d enu = Eigen::Vector3d::Zero();
  Quality quality = Quality::NONE;
};

}  // namespace gnss_core
```

- [ ] **Step 2: 写 package.xml**

```xml
<?xml version="1.0"?>
<package format="3">
  <name>gnss_core</name>
  <version>0.1.0</version>
  <description>Framework-free GNSS algorithms (no ROS, no GLIM)</description>
  <maintainer email="dev@example.com">dev</maintainer>
  <license>Apache-2.0</license>

  <buildtool_depend>ament_cmake</buildtool_depend>
  <depend>eigen</depend>
  <test_depend>ament_cmake_gtest</test_depend>

  <export>
    <build_type>ament_cmake</build_type>
  </export>
</package>
```

- [ ] **Step 3: 写 CMakeLists.txt(库 + 依赖发现)**

注:GeographicLib 用 Find 模块(非 Config),须先把其 cmake 目录加入 `CMAKE_MODULE_PATH`。

```cmake
cmake_minimum_required(VERSION 3.8)
project(gnss_core)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(ament_cmake REQUIRED)
find_package(Eigen3 REQUIRED)
find_package(GTSAM REQUIRED)
list(APPEND CMAKE_MODULE_PATH "/usr/share/cmake/geographiclib")
find_package(GeographicLib REQUIRED)

add_library(gnss_core SHARED
  src/geodetic.cpp
  src/rtk_fix_buffer.cpp
  src/rtk_noise_policy.cpp
  src/frame_aligner.cpp
  src/trajectory_compare.cpp
  src/pos_io.cpp
)
target_include_directories(gnss_core PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include>
  ${GeographicLib_INCLUDE_DIRS}
)
target_link_libraries(gnss_core Eigen3::Eigen gtsam ${GeographicLib_LIBRARIES})

install(DIRECTORY include/ DESTINATION include)
install(TARGETS gnss_core EXPORT gnss_core-targets
  LIBRARY DESTINATION lib ARCHIVE DESTINATION lib RUNTIME DESTINATION bin)
ament_export_targets(gnss_core-targets HAS_LIBRARY_TARGET)
ament_export_dependencies(Eigen3 GTSAM)

if(BUILD_TESTING)
  find_package(ament_cmake_gtest REQUIRED)
  ament_add_gtest(test_types test/test_types.cpp)
  target_link_libraries(test_types gnss_core)
endif()

ament_package()
```

因 CMakeLists 引用了尚未创建的 src 文件,先建空实现占位以便本 Task 能编译。后续 Task 会填。

- [ ] **Step 4: 建空实现占位**

为 `geodetic/rtk_fix_buffer/rtk_noise_policy/frame_aligner/trajectory_compare/pos_io` 各建一个仅含 `#include` 对应头文件的空 `.cpp`,头文件先建最小空壳(仅 `#pragma once` + namespace)。这些在各自 Task 中填实。types.hpp 已完整。

- [ ] **Step 5: 写失败测试 test_types.cpp**

```cpp
#include <gtest/gtest.h>
#include "gnss_core/types.hpp"

TEST(Types, QualityEnumValues) {
  EXPECT_EQ(static_cast<uint8_t>(gnss_core::Quality::NONE), 0);
  EXPECT_EQ(static_cast<uint8_t>(gnss_core::Quality::FIXED), 4);
}

TEST(Types, RtkFixSampleDefaults) {
  gnss_core::RtkFixSample s;
  EXPECT_EQ(s.quality, gnss_core::Quality::NONE);
  EXPECT_FALSE(s.heading_valid);
}
```

- [ ] **Step 6: 构建并跑测试**

Run: `cd /home/steve/driver_ws && colcon build --packages-select gnss_core && colcon test --packages-select gnss_core --event-handlers console_direct+`
Expected: 构建成功,test_types 2 passed。**这一步同时验证了 GTSAM/GeographicLib 的 find_package 链路(spec §13 首个风险)。**

- [ ] **Step 7: Commit**

```bash
cd /home/steve/driver_ws && git add src/gnss_core && \
git commit -m "feat(gnss_core): package skeleton + core types"
```

---

### Task 3: geodetic(LlaToEnu 封装 GeographicLib)

**Files:**
- Modify: `gnss_core/include/gnss_core/geodetic.hpp`
- Modify: `gnss_core/src/geodetic.cpp`
- Test: `gnss_core/test/test_geodetic.cpp`(新建,并在 CMakeLists 注册)

**Interfaces:**
- Consumes: 无
- Produces: `class LlaToEnu { LlaToEnu(double lat0,double lon0,double alt0); Eigen::Vector3d forward(double lat,double lon,double alt) const; };`

- [ ] **Step 1: 写头文件**

```cpp
#pragma once
#include <Eigen/Core>
#include <memory>

namespace GeographicLib { class LocalCartesian; }

namespace gnss_core {

// 经纬高 → 局部 ENU(米)。原点固定于构造时给定的 lat0/lon0/alt0。
class LlaToEnu {
public:
  LlaToEnu(double lat0, double lon0, double alt0);
  ~LlaToEnu();
  Eigen::Vector3d forward(double lat, double lon, double alt) const;  // 返回 [E,N,U]
private:
  std::unique_ptr<GeographicLib::LocalCartesian> impl_;
};

}  // namespace gnss_core
```

- [ ] **Step 2: 写失败测试 test_geodetic.cpp**

```cpp
#include <gtest/gtest.h>
#include "gnss_core/geodetic.hpp"

TEST(Geodetic, OriginIsZero) {
  gnss_core::LlaToEnu conv(44.5, 90.28, 617.0);
  const auto p = conv.forward(44.5, 90.28, 617.0);
  EXPECT_NEAR(p.norm(), 0.0, 1e-6);
}

TEST(Geodetic, OneMetreNorth) {
  gnss_core::LlaToEnu conv(44.5, 90.28, 617.0);
  const double dlat = 1.0 / 111320.0;   // ≈ 1 m 纬度
  const auto p = conv.forward(44.5 + dlat, 90.28, 617.0);
  EXPECT_NEAR(p.x(), 0.0, 0.02);        // E
  EXPECT_NEAR(p.y(), 1.0, 0.02);        // N
  EXPECT_NEAR(p.z(), 0.0, 0.02);        // U
}
```

在 CMakeLists 的 `if(BUILD_TESTING)` 块内添加:
```cmake
  ament_add_gtest(test_geodetic test/test_geodetic.cpp)
  target_link_libraries(test_geodetic gnss_core)
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd /home/steve/driver_ws && colcon build --packages-select gnss_core --cmake-args -DBUILD_TESTING=ON && colcon test --packages-select gnss_core --ctest-args -R test_geodetic --event-handlers console_direct+`
Expected: 链接失败或断言失败(forward 未实现)。

- [ ] **Step 4: 写实现 geodetic.cpp**

```cpp
#include "gnss_core/geodetic.hpp"
#include <GeographicLib/LocalCartesian.hpp>

namespace gnss_core {

LlaToEnu::LlaToEnu(double lat0, double lon0, double alt0)
  : impl_(std::make_unique<GeographicLib::LocalCartesian>(lat0, lon0, alt0)) {}

LlaToEnu::~LlaToEnu() = default;

Eigen::Vector3d LlaToEnu::forward(double lat, double lon, double alt) const {
  double e, n, u;
  impl_->Forward(lat, lon, alt, e, n, u);
  return {e, n, u};
}

}  // namespace gnss_core
```

- [ ] **Step 5: 跑测试确认通过**

Run: 同 Step 3
Expected: test_geodetic 2 passed。

- [ ] **Step 6: Commit**

```bash
cd /home/steve/driver_ws && git add src/gnss_core && \
git commit -m "feat(gnss_core): LlaToEnu via GeographicLib::LocalCartesian"
```

---

### Task 4: RtkFixBuffer(时间插值,质量取较差者)

**Files:**
- Modify: `gnss_core/include/gnss_core/rtk_fix_buffer.hpp`
- Modify: `gnss_core/src/rtk_fix_buffer.cpp`
- Test: `gnss_core/test/test_rtk_fix_buffer.cpp`

**Interfaces:**
- Consumes: `RtkFixSample`, `Quality`(types.hpp)
- Produces: `class RtkFixBuffer { void push(const RtkFixSample&); std::optional<RtkFixSample> interpolate(double t) const; void prune(double horizon_s, double now); };`
  - `interpolate`:t 落在两样本之间→线性插值 lat/lon/alt/sigma/diff_age,**quality 取两端较差者(数值较小者)**;t 越界或缓冲不足→`std::nullopt`。

- [ ] **Step 1: 写头文件**

```cpp
#pragma once
#include <deque>
#include <optional>
#include "gnss_core/types.hpp"

namespace gnss_core {

class RtkFixBuffer {
public:
  void push(const RtkFixSample& s);              // 按 stamp 递增维护
  std::optional<RtkFixSample> interpolate(double t) const;
  void prune(double horizon_s, double now);      // 丢弃 stamp < now - horizon_s
  size_t size() const { return buf_.size(); }
private:
  std::deque<RtkFixSample> buf_;
};

}  // namespace gnss_core
```

- [ ] **Step 2: 写失败测试**

```cpp
#include <gtest/gtest.h>
#include "gnss_core/rtk_fix_buffer.hpp"
using namespace gnss_core;

static RtkFixSample mk(double t, Quality q, double lat) {
  RtkFixSample s; s.stamp = t; s.quality = q; s.lat = lat; return s;
}

TEST(RtkFixBuffer, InterpolatesMidpoint) {
  RtkFixBuffer b;
  b.push(mk(100.0, Quality::FIXED, 44.0));
  b.push(mk(102.0, Quality::FIXED, 46.0));
  auto r = b.interpolate(101.0);
  ASSERT_TRUE(r.has_value());
  EXPECT_NEAR(r->lat, 45.0, 1e-9);
}

TEST(RtkFixBuffer, QualityTakesWorseOfEnds) {
  RtkFixBuffer b;
  b.push(mk(100.0, Quality::FIXED, 44.0));
  b.push(mk(102.0, Quality::SINGLE, 46.0));
  auto r = b.interpolate(101.0);
  ASSERT_TRUE(r.has_value());
  EXPECT_EQ(r->quality, Quality::SINGLE);   // 较差者
}

TEST(RtkFixBuffer, OutOfRangeReturnsNullopt) {
  RtkFixBuffer b;
  b.push(mk(100.0, Quality::FIXED, 44.0));
  b.push(mk(102.0, Quality::FIXED, 46.0));
  EXPECT_FALSE(b.interpolate(105.0).has_value());
  EXPECT_FALSE(b.interpolate(99.0).has_value());
}

TEST(RtkFixBuffer, PruneDropsOld) {
  RtkFixBuffer b;
  b.push(mk(100.0, Quality::FIXED, 44.0));
  b.push(mk(160.0, Quality::FIXED, 46.0));
  b.prune(30.0, 161.0);                     // 丢弃 < 131
  EXPECT_EQ(b.size(), 1u);
}
```

在 CMakeLists 注册 `test_rtk_fix_buffer`(同 Task 3 Step 2 模式)。

- [ ] **Step 3: 跑测试确认失败**

Run: `cd /home/steve/driver_ws && colcon build --packages-select gnss_core --cmake-args -DBUILD_TESTING=ON && colcon test --packages-select gnss_core --ctest-args -R test_rtk_fix_buffer --event-handlers console_direct+`
Expected: FAIL。

- [ ] **Step 4: 写实现 rtk_fix_buffer.cpp**

```cpp
#include "gnss_core/rtk_fix_buffer.hpp"
#include <algorithm>

namespace gnss_core {

void RtkFixBuffer::push(const RtkFixSample& s) {
  // 常规为递增到达;若乱序则插入到正确位置
  if (buf_.empty() || s.stamp >= buf_.back().stamp) { buf_.push_back(s); return; }
  auto it = std::lower_bound(buf_.begin(), buf_.end(), s.stamp,
      [](const RtkFixSample& a, double t){ return a.stamp < t; });
  buf_.insert(it, s);
}

std::optional<RtkFixSample> RtkFixBuffer::interpolate(double t) const {
  if (buf_.size() < 2) return std::nullopt;
  if (t < buf_.front().stamp || t > buf_.back().stamp) return std::nullopt;
  auto right = std::lower_bound(buf_.begin(), buf_.end(), t,
      [](const RtkFixSample& a, double tt){ return a.stamp < tt; });
  if (right == buf_.begin()) return *right;          // t == front
  auto left = right - 1;
  const double tl = left->stamp, tr = right->stamp;
  const double p = (tr > tl) ? (t - tl) / (tr - tl) : 0.0;
  RtkFixSample out;
  out.stamp = t;
  out.lat = (1 - p) * left->lat + p * right->lat;
  out.lon = (1 - p) * left->lon + p * right->lon;
  out.alt = (1 - p) * left->alt + p * right->alt;
  out.sigma_enu = (1 - p) * left->sigma_enu + p * right->sigma_enu;
  out.diff_age = (1 - p) * left->diff_age + p * right->diff_age;
  out.sats_used = std::min(left->sats_used, right->sats_used);
  // quality 取较差者(枚举数值较小者)
  out.quality = static_cast<Quality>(std::min(
      static_cast<uint8_t>(left->quality), static_cast<uint8_t>(right->quality)));
  out.heading = (1 - p) * left->heading + p * right->heading;
  out.heading_valid = left->heading_valid && right->heading_valid;
  return out;
}

void RtkFixBuffer::prune(double horizon_s, double now) {
  const double cutoff = now - horizon_s;
  while (!buf_.empty() && buf_.front().stamp < cutoff) buf_.pop_front();
}

}  // namespace gnss_core
```

- [ ] **Step 5: 跑测试确认通过**

Run: 同 Step 3
Expected: 4 passed。

- [ ] **Step 6: Commit**

```bash
cd /home/steve/driver_ws && git add src/gnss_core && \
git commit -m "feat(gnss_core): RtkFixBuffer with time interpolation"
```

---

### Task 5: RtkNoisePolicy(门限 + 质量缩放 + 鲁棒核)

**Files:**
- Modify: `gnss_core/include/gnss_core/rtk_noise_policy.hpp`
- Modify: `gnss_core/src/rtk_noise_policy.cpp`
- Test: `gnss_core/test/test_rtk_noise_policy.cpp`

**Interfaces:**
- Consumes: `RtkFixSample`, `Quality`
- Produces:
```cpp
struct NoisePolicyConfig {
  int min_quality = 3;                    // FLOAT
  double max_diff_age = 15.0;
  int min_sats = 6;
  std::array<double,5> quality_sigma_scale = {0.0, 50.0, 20.0, 5.0, 1.0};
  Eigen::Vector3d sigma_floor = {0.02, 0.02, 0.05};
  double vertical_scale = 3.0;
  std::string robust_kernel = "huber";    // none|huber|cauchy
  double robust_delta = 1.345;
};
class RtkNoisePolicy {
public:
  explicit RtkNoisePolicy(const NoisePolicyConfig& cfg);
  // 通过门限则返回 noise model,否则 nullptr
  gtsam::SharedNoiseModel evaluate(const RtkFixSample& s) const;
private:
  NoisePolicyConfig cfg_;
};
```

- [ ] **Step 1: 写头文件**(内容同上 Interfaces,加 `#include <gtsam/linear/NoiseModel.h>` 与 `<array>`)

- [ ] **Step 2: 写失败测试**

```cpp
#include <gtest/gtest.h>
#include "gnss_core/rtk_noise_policy.hpp"
using namespace gnss_core;

static RtkFixSample good() {
  RtkFixSample s;
  s.quality = Quality::FIXED; s.diff_age = 1.0; s.sats_used = 20;
  s.sigma_enu = {0.01, 0.01, 0.02};
  return s;
}

TEST(NoisePolicy, RejectsBelowMinQuality) {
  RtkNoisePolicy p{NoisePolicyConfig{}};
  auto s = good(); s.quality = Quality::SINGLE;
  EXPECT_EQ(p.evaluate(s), nullptr);
}

TEST(NoisePolicy, RejectsStaleDiffAge) {
  RtkNoisePolicy p{NoisePolicyConfig{}};
  auto s = good(); s.diff_age = 30.0;
  EXPECT_EQ(p.evaluate(s), nullptr);
}

TEST(NoisePolicy, RejectsFewSats) {
  RtkNoisePolicy p{NoisePolicyConfig{}};
  auto s = good(); s.sats_used = 4;
  EXPECT_EQ(p.evaluate(s), nullptr);
}

TEST(NoisePolicy, AcceptsFixedAndAppliesFloor) {
  NoisePolicyConfig cfg;                    // sigma_floor E/N=0.02
  RtkNoisePolicy p{cfg};
  auto s = good(); s.sigma_enu = {0.001, 0.001, 0.001};  // 板卡报 1mm
  auto m = p.evaluate(s);
  ASSERT_NE(m, nullptr);
  // 剥出鲁棒核下的高斯 sigma;floor 抬到 0.02(E/N)、0.05*3(U)
  auto robust = std::dynamic_pointer_cast<gtsam::noiseModel::Robust>(m);
  ASSERT_NE(robust, nullptr);
  auto diag = std::dynamic_pointer_cast<const gtsam::noiseModel::Diagonal>(robust->noise());
  ASSERT_NE(diag, nullptr);
  EXPECT_NEAR(diag->sigmas()(0), 0.02, 1e-9);
  EXPECT_NEAR(diag->sigmas()(2), 0.05 * 3.0, 1e-9);   // vertical_scale
}

TEST(NoisePolicy, FloatScalesSigmaFiveX) {
  NoisePolicyConfig cfg; cfg.min_quality = 3;
  RtkNoisePolicy p{cfg};
  auto s = good(); s.quality = Quality::FLOAT; s.sigma_enu = {0.1, 0.1, 0.1};
  auto m = p.evaluate(s);
  ASSERT_NE(m, nullptr);
  auto robust = std::dynamic_pointer_cast<gtsam::noiseModel::Robust>(m);
  auto diag = std::dynamic_pointer_cast<const gtsam::noiseModel::Diagonal>(robust->noise());
  EXPECT_NEAR(diag->sigmas()(0), 0.1 * 5.0, 1e-9);     // FLOAT scale=5
}
```

在 CMakeLists 注册 `test_rtk_noise_policy`。

- [ ] **Step 3: 跑测试确认失败**

Run: `cd /home/steve/driver_ws && colcon build --packages-select gnss_core --cmake-args -DBUILD_TESTING=ON && colcon test --packages-select gnss_core --ctest-args -R test_rtk_noise_policy --event-handlers console_direct+`
Expected: FAIL。

- [ ] **Step 4: 写实现 rtk_noise_policy.cpp**

```cpp
#include "gnss_core/rtk_noise_policy.hpp"
#include <gtsam/linear/NoiseModel.h>
#include <algorithm>

namespace gnss_core {

RtkNoisePolicy::RtkNoisePolicy(const NoisePolicyConfig& cfg) : cfg_(cfg) {}

gtsam::SharedNoiseModel RtkNoisePolicy::evaluate(const RtkFixSample& s) const {
  const int q = static_cast<int>(s.quality);
  if (q < cfg_.min_quality) return nullptr;
  if (s.diff_age > cfg_.max_diff_age) return nullptr;
  if (s.sats_used < cfg_.min_sats) return nullptr;

  const double scale = cfg_.quality_sigma_scale.at(q);
  if (scale <= 0.0) return nullptr;         // 防零 σ / 无穷权重(spec §7.5 约束)

  Eigen::Vector3d sigma = s.sigma_enu * scale;
  sigma = sigma.cwiseMax(cfg_.sigma_floor);
  sigma(2) *= cfg_.vertical_scale;

  gtsam::SharedNoiseModel base = gtsam::noiseModel::Diagonal::Sigmas(sigma);
  if (cfg_.robust_kernel == "none") return base;
  gtsam::noiseModel::mEstimator::Base::shared_ptr m;
  if (cfg_.robust_kernel == "cauchy")
    m = gtsam::noiseModel::mEstimator::Cauchy::Create(cfg_.robust_delta);
  else
    m = gtsam::noiseModel::mEstimator::Huber::Create(cfg_.robust_delta);
  return gtsam::noiseModel::Robust::Create(m, base);
}

}  // namespace gnss_core
```

- [ ] **Step 5: 跑测试确认通过**

Run: 同 Step 3
Expected: 5 passed。

- [ ] **Step 6: Commit**

```bash
cd /home/steve/driver_ws && git add src/gnss_core && \
git commit -m "feat(gnss_core): RtkNoisePolicy (gates + quality scaling + robust)"
```

---

### Task 6: FrameAligner(SVD 求 T_world_enu)

**Files:**
- Modify: `gnss_core/include/gnss_core/frame_aligner.hpp`
- Modify: `gnss_core/src/frame_aligner.cpp`
- Test: `gnss_core/test/test_frame_aligner.cpp`

**Interfaces:**
- Consumes: 无(纯几何)
- Produces:
```cpp
class FrameAligner {
public:
  explicit FrameAligner(double min_baseline);
  void add(const Eigen::Vector3d& submap_xyz, const Eigen::Vector3d& enu);
  bool initialized() const;
  // 已初始化后返回 T_world_enu(把 ENU 坐标映射到 world);未初始化返回 identity
  Eigen::Isometry3d T_world_enu() const;
private:
  double min_baseline_;
  bool initialized_ = false;
  Eigen::Isometry3d T_world_enu_ = Eigen::Isometry3d::Identity();
  std::vector<Eigen::Vector3d> est_, enu_;
};
```
- 语义:累积成对点,当 `est_` 首尾间距 > `min_baseline` 时用 2D Umeyama(仅 yaw + 平移,z 不参与旋转)一次性求解 `T_world_enu`,之后固定。移植自 `gnss_global` 的 SVD 逻辑。

- [ ] **Step 1: 写头文件**(同上 Interfaces,加 `#include <Eigen/Geometry>` `<vector>`)

- [ ] **Step 2: 写失败测试**

```cpp
#include <gtest/gtest.h>
#include "gnss_core/frame_aligner.hpp"

TEST(FrameAligner, RecoversKnownTransform) {
  // 构造已知:world = Rz(30°) * enu + t
  const double a = 30.0 * M_PI / 180.0;
  Eigen::Matrix3d R = Eigen::Matrix3d::Identity();
  R.block<2,2>(0,0) << std::cos(a), -std::sin(a), std::sin(a), std::cos(a);
  Eigen::Vector3d t(10.0, -5.0, 2.0);
  Eigen::Isometry3d T_world_enu_true = Eigen::Isometry3d::Identity();
  T_world_enu_true.linear() = R; T_world_enu_true.translation() = t;

  gnss_core::FrameAligner al(10.0);
  std::vector<Eigen::Vector3d> enus = {
    {0,0,0},{5,0,0},{10,0,0},{15,3,0},{20,6,1}};   // 首尾 > 10m
  for (const auto& e : enus) {
    Eigen::Vector3d world = T_world_enu_true * e;    // submap 位置 = world 真值
    al.add(world, e);
  }
  ASSERT_TRUE(al.initialized());
  const auto T = al.T_world_enu();
  // 用它把 enu 变到 world,应与真值一致
  for (const auto& e : enus) {
    EXPECT_LT((T * e - T_world_enu_true * e).norm(), 0.1);
  }
}

TEST(FrameAligner, NotInitializedBelowBaseline) {
  gnss_core::FrameAligner al(10.0);
  al.add({0,0,0},{0,0,0});
  al.add({1,0,0},{1,0,0});          // 基线仅 1m
  EXPECT_FALSE(al.initialized());
}
```

在 CMakeLists 注册 `test_frame_aligner`。

- [ ] **Step 3: 跑测试确认失败**

Run: `cd /home/steve/driver_ws && colcon build --packages-select gnss_core --cmake-args -DBUILD_TESTING=ON && colcon test --packages-select gnss_core --ctest-args -R test_frame_aligner --event-handlers console_direct+`
Expected: FAIL。

- [ ] **Step 4: 写实现 frame_aligner.cpp**

```cpp
#include "gnss_core/frame_aligner.hpp"

namespace gnss_core {

FrameAligner::FrameAligner(double min_baseline) : min_baseline_(min_baseline) {}

void FrameAligner::add(const Eigen::Vector3d& submap_xyz, const Eigen::Vector3d& enu) {
  est_.push_back(submap_xyz);
  enu_.push_back(enu);
  if (initialized_ || est_.size() < 2) return;
  if ((est_.back() - est_.front()).norm() < min_baseline_) return;

  // 2D Umeyama(仅 yaw + 平移):在 XY 平面上对齐 enu → est
  Eigen::Vector3d mean_est = Eigen::Vector3d::Zero(), mean_enu = Eigen::Vector3d::Zero();
  for (size_t i = 0; i < est_.size(); ++i) { mean_est += est_[i]; mean_enu += enu_[i]; }
  mean_est /= est_.size(); mean_enu /= enu_.size();

  Eigen::Matrix2d cov = Eigen::Matrix2d::Zero();
  for (size_t i = 0; i < est_.size(); ++i)
    cov += (est_[i].head<2>() - mean_est.head<2>()) * (enu_[i].head<2>() - mean_enu.head<2>()).transpose();

  Eigen::JacobiSVD<Eigen::Matrix2d> svd(cov, Eigen::ComputeFullU | Eigen::ComputeFullV);
  Eigen::Matrix2d R2 = svd.matrixU() * svd.matrixV().transpose();
  if (R2.determinant() < 0) { Eigen::Matrix2d V = svd.matrixV(); V.col(1) *= -1; R2 = svd.matrixU() * V.transpose(); }

  Eigen::Matrix3d R = Eigen::Matrix3d::Identity();
  R.block<2,2>(0,0) = R2;
  T_world_enu_ = Eigen::Isometry3d::Identity();
  T_world_enu_.linear() = R;
  T_world_enu_.translation() = mean_est - R * mean_enu;
  initialized_ = true;
}

bool FrameAligner::initialized() const { return initialized_; }
Eigen::Isometry3d FrameAligner::T_world_enu() const { return T_world_enu_; }

}  // namespace gnss_core
```

- [ ] **Step 5: 跑测试确认通过**

Run: 同 Step 3
Expected: 2 passed。

- [ ] **Step 6: Commit**

```bash
cd /home/steve/driver_ws && git add src/gnss_core && \
git commit -m "feat(gnss_core): FrameAligner (2D Umeyama T_world_enu)"
```

---

### Task 7: AntennaPriorFactor(带杆臂,Jacobian 数值校验)

**Files:**
- Modify: `gnss_core/include/gnss_core/antenna_prior_factor.hpp`(header-only)
- Test: `gnss_core/test/test_antenna_prior_factor.cpp`

**Interfaces:**
- Consumes: 无
- Produces:
```cpp
class AntennaPriorFactor : public gtsam::NoiseModelFactorN<gtsam::Pose3> {
public:
  AntennaPriorFactor(gtsam::Key key, const Eigen::Vector3d& measured_world,
                     const Eigen::Vector3d& lever_imu, const gtsam::SharedNoiseModel& model);
  gtsam::Vector evaluateError(const gtsam::Pose3& X,
                              gtsam::OptionalMatrixType H) const override;
};
```
- 误差:`h(X) = X.translation() + X.rotation() * lever_imu`;残差 `h(X) - measured_world`。lever=0 时退化为纯平移先验。

- [ ] **Step 1: 写头文件(header-only 实现)**

```cpp
#pragma once
#include <gtsam/nonlinear/NonlinearFactor.h>
#include <gtsam/geometry/Pose3.h>
#include <Eigen/Core>

namespace gnss_core {

class AntennaPriorFactor : public gtsam::NoiseModelFactorN<gtsam::Pose3> {
  gtsam::Point3 measured_;
  gtsam::Point3 lever_;
public:
  using Base = gtsam::NoiseModelFactorN<gtsam::Pose3>;
  AntennaPriorFactor(gtsam::Key key, const Eigen::Vector3d& measured_world,
                     const Eigen::Vector3d& lever_imu, const gtsam::SharedNoiseModel& model)
    : Base(model, key), measured_(measured_world), lever_(lever_imu) {}

  gtsam::Vector evaluateError(const gtsam::Pose3& X,
                              gtsam::OptionalMatrixType H) const override {
    gtsam::Matrix36 Hpred;   // d(predicted)/d(pose)
    // 天线在 world 系的位置 = X 变换 lever(body 点)
    const gtsam::Point3 predicted = X.transformFrom(lever_, H ? &Hpred : nullptr);
    if (H) *H = Hpred;
    return predicted - measured_;
  }
};

}  // namespace gnss_core
```

- [ ] **Step 2: 写 Jacobian 数值校验测试**

```cpp
#include <gtest/gtest.h>
#include <gtsam/base/numericalDerivative.h>
#include <gtsam/linear/NoiseModel.h>
#include "gnss_core/antenna_prior_factor.hpp"
using namespace gtsam;

TEST(AntennaPriorFactor, JacobianMatchesNumerical) {
  Key k = 0;
  Eigen::Vector3d measured(1.0, 2.0, 3.0), lever(0.5, -0.2, 0.1);
  auto model = noiseModel::Isotropic::Sigma(3, 0.05);
  gnss_core::AntennaPriorFactor f(k, measured, lever, model);

  Pose3 X(Rot3::RzRyRx(0.3, -0.1, 0.2), Point3(1.0, 1.0, 1.0));
  Matrix H;
  f.evaluateError(X, &H);
  Matrix Hnum = numericalDerivative11<Vector, Pose3>(
      [&](const Pose3& p){ return f.evaluateError(p, OptionalMatrixType(nullptr)); }, X);
  EXPECT_TRUE(assert_equal(Hnum, H, 1e-6));
}

TEST(AntennaPriorFactor, ZeroLeverEqualsTranslationResidual) {
  Key k = 0;
  Eigen::Vector3d measured(1.0, 2.0, 3.0), lever(0,0,0);
  auto model = noiseModel::Isotropic::Sigma(3, 0.05);
  gnss_core::AntennaPriorFactor f(k, measured, lever, model);
  Pose3 X(Rot3(), Point3(1.5, 2.5, 3.5));
  Vector e = f.evaluateError(X, OptionalMatrixType(nullptr));
  EXPECT_TRUE(assert_equal(Vector(Point3(0.5, 0.5, 0.5)), e, 1e-9));
}
```

在 CMakeLists 注册 `test_antenna_prior_factor`。

> 注:GTSAM 4.3 用 `NoiseModelFactorN` 与 `OptionalMatrixType`;若实现时编译报接口不符,以 `/usr/local/include/gtsam/nonlinear/NonlinearFactor.h` 的实际签名为准调整(这是本 Task 唯一的 API 风险点)。

- [ ] **Step 3: 跑测试确认失败**(工厂头未纳入编译前)

Run: `cd /home/steve/driver_ws && colcon build --packages-select gnss_core --cmake-args -DBUILD_TESTING=ON && colcon test --packages-select gnss_core --ctest-args -R test_antenna_prior_factor --event-handlers console_direct+`
Expected: 编译失败(测试引用未注册)或断言前失败。

- [ ] **Step 4: 确保头文件编入**(header-only,无需改 .cpp;确认 CMakeLists 测试目标链接 gnss_core 与 gtsam)

- [ ] **Step 5: 跑测试确认通过**

Run: 同 Step 3
Expected: 2 passed(Jacobian 数值一致 + 零杆臂退化)。

- [ ] **Step 6: Commit**

```bash
cd /home/steve/driver_ws && git add src/gnss_core && \
git commit -m "feat(gnss_core): AntennaPriorFactor with numerical-verified Jacobian"
```

---

### Task 8: 驱动增发 RtkFix

**Files:**
- Modify: `driver_ws/src/gnss_CGI610/src/gnss_can_node.cpp`
- Modify: `driver_ws/src/gnss_CGI610/CMakeLists.txt`(加 `gnss_msgs` 依赖)
- Modify: `driver_ws/src/gnss_CGI610/package.xml`(加 `<depend>gnss_msgs</depend>`)
- Test: `driver_ws/src/gnss_CGI610/test/test_rtk_fix_mapping.cpp`(新建)

**Interfaces:**
- Consumes: `gnss_msgs/msg/RtkFix`(Task 1)、`cgi610::Cycle`(现有)、`cgi610::SatStatus`(现有)
- Produces: topic `~/rtk_fix`;一个可单测的纯映射函数 `gnss_msgs::msg::RtkFix MapCycleToRtkFix(const cgi610::Cycle& c)`

- [ ] **Step 1: 写失败测试(纯映射函数)**

新建 `test/test_rtk_fix_mapping.cpp`:
```cpp
#include <gtest/gtest.h>
#include "gnss_can_node_mapping.hpp"   // 下一步抽出的纯函数头
#include "cgi610/cgi610_decoder.hpp"

TEST(RtkFixMapping, FixedWithHeading) {
  cgi610::Cycle c;
  c.satellite_status = static_cast<uint8_t>(cgi610::SatStatus::RTK_FIXED);
  c.lat_deg = 44.5; c.lon_deg = 90.28; c.alt_m = 617.0;
  c.pos_sigma_enu_m[0] = 0.01; c.pos_sigma_enu_m[1] = 0.012; c.pos_sigma_enu_m[2] = 0.03;
  c.gps_age_s = 0.8; c.sats_used = 20; c.heading_deg = 123.4; c.att_sigma_deg[0] = 0.2;
  auto m = cgi610::MapCycleToRtkFix(c);
  EXPECT_EQ(m.quality, gnss_msgs::msg::RtkFix::QUALITY_FIXED);
  EXPECT_TRUE(m.heading_valid);
  EXPECT_NEAR(m.sigma_enu[0], 0.01, 1e-9);
  EXPECT_NEAR(m.diff_age, 0.8, 1e-6);
}

TEST(RtkFixMapping, FloatNoHeadingClearsHeadingValid) {
  cgi610::Cycle c;
  c.satellite_status = static_cast<uint8_t>(cgi610::SatStatus::RTK_FLOAT_NO_HEADING);
  auto m = cgi610::MapCycleToRtkFix(c);
  EXPECT_EQ(m.quality, gnss_msgs::msg::RtkFix::QUALITY_FLOAT);
  EXPECT_FALSE(m.heading_valid);
}

TEST(RtkFixMapping, SingleMapsToSingle) {
  cgi610::Cycle c;
  c.satellite_status = static_cast<uint8_t>(cgi610::SatStatus::SINGLE);
  EXPECT_EQ(cgi610::MapCycleToRtkFix(c).quality, gnss_msgs::msg::RtkFix::QUALITY_SINGLE);
}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /home/steve/driver_ws && colcon build --packages-select gnss_CGI610 --cmake-args -DBUILD_TESTING=ON`
Expected: 编译失败(`gnss_can_node_mapping.hpp` / `MapCycleToRtkFix` 不存在)。

- [ ] **Step 3: 抽出纯映射函数头 gnss_can_node_mapping.hpp**

`include/gnss_can_node_mapping.hpp`:
```cpp
#pragma once
#include <gnss_msgs/msg/rtk_fix.hpp>
#include "cgi610/cgi610_decoder.hpp"

namespace cgi610 {

inline gnss_msgs::msg::RtkFix MapCycleToRtkFix(const Cycle& c) {
  gnss_msgs::msg::RtkFix m;
  using S = SatStatus; using Q = gnss_msgs::msg::RtkFix;
  switch (static_cast<S>(c.satellite_status)) {
    case S::RTK_FIXED: case S::RTK_FIXED_NO_HEADING: m.quality = Q::QUALITY_FIXED; break;
    case S::RTK_FLOAT: case S::RTK_FLOAT_NO_HEADING: m.quality = Q::QUALITY_FLOAT; break;
    case S::PSRDIFF:   case S::PSRDIFF_NO_HEADING:   m.quality = Q::QUALITY_DGPS;  break;
    case S::SINGLE: case S::SINGLE_NO_HEADING: case S::COMBINED_DR: m.quality = Q::QUALITY_SINGLE; break;
    default: m.quality = Q::QUALITY_NONE; break;
  }
  m.raw_status = c.satellite_status;
  const S s = static_cast<S>(c.satellite_status);
  m.heading_valid = (s == S::RTK_FIXED || s == S::RTK_FLOAT ||
                     s == S::PSRDIFF || s == S::SINGLE);
  m.latitude = c.lat_deg; m.longitude = c.lon_deg; m.altitude = c.alt_m;
  m.sigma_enu = {c.pos_sigma_enu_m[0], c.pos_sigma_enu_m[1], c.pos_sigma_enu_m[2]};
  m.diff_age = static_cast<float>(c.gps_age_s);
  m.sats_used = c.sats_used; m.sats_main = c.sats_main; m.sats_aux = c.sats_aux;
  m.heading = static_cast<float>(c.heading_deg);
  m.heading_sigma = static_cast<float>(c.att_sigma_deg[0]);
  return m;
}

}  // namespace cgi610
```

在 CMakeLists 注册测试:
```cmake
if(BUILD_TESTING)
  find_package(ament_cmake_gtest REQUIRED)
  find_package(gnss_msgs REQUIRED)
  ament_add_gtest(test_rtk_fix_mapping test/test_rtk_fix_mapping.cpp)
  target_include_directories(test_rtk_fix_mapping PRIVATE include src)
  ament_target_dependencies(test_rtk_fix_mapping gnss_msgs)
endif()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /home/steve/driver_ws && colcon build --packages-select gnss_CGI610 --cmake-args -DBUILD_TESTING=ON && colcon test --packages-select gnss_CGI610 --ctest-args -R test_rtk_fix_mapping --event-handlers console_direct+`
Expected: 3 passed。

- [ ] **Step 5: 在节点里接线增发**

`gnss_can_node.cpp`:加 `#include "gnss_can_node_mapping.hpp"`;在构造函数建 publisher `rtk_fix_pub_ = create_publisher<gnss_msgs::msg::RtkFix>("~/rtk_fix", qos);`;在填完 `NavSatFix fix` 后追加:
```cpp
auto rtk = cgi610::MapCycleToRtkFix(c);
rtk.header.stamp = stamp;
rtk.header.frame_id = frame_id_;
rtk_fix_pub_->publish(rtk);
```
在 `package.xml` 加 `<depend>gnss_msgs</depend>`;`CMakeLists.txt` 的 `ament_target_dependencies(gnss_can_node ...)` 加 `gnss_msgs`。

- [ ] **Step 6: 构建 + 冒烟(有 bag 时回放,无 bag 则仅确认节点起来且 topic 存在)**

Run: `cd /home/steve/driver_ws && colcon build --packages-select gnss_CGI610 && source install/setup.bash`
Expected: 构建成功。若有含 CAN 的 bag:`ros2 topic echo /<node>/rtk_fix` 能看到 quality 字段随解状态变化。

- [ ] **Step 7: Commit**

```bash
cd /home/steve/driver_ws && git add src/gnss_CGI610 && \
git commit -m "feat(gnss_CGI610): publish gnss_msgs/RtkFix alongside NavSatFix"
```

---

### Task 9: rtk_global 模块壳

**Files:**
- Create: `glim_ws/src/glim_ext/modules/mapping/rtk_global/include/glim_ext/rtk_global_module.hpp`
- Create: `glim_ws/src/glim_ext/modules/mapping/rtk_global/src/glim_ext/rtk_global_module_ros2.cpp`
- Create: `glim_ws/src/glim_ext/modules/mapping/rtk_global/CMakeLists.txt`
- Create: `glim_ws/src/glim_ext/modules/mapping/rtk_global/package.xml`
- Create: `glim_ws/src/glim_ext/config/config_rtk_global.json`

**Interfaces:**
- Consumes: `gnss_core::{RtkFixBuffer, RtkNoisePolicy, FrameAligner, AntennaPriorFactor, LlaToEnu, RtkFixSample, Quality, NoisePolicyConfig}`;`gnss_msgs/msg/RtkFix`;GLIM `ExtensionModuleROS2`、`GlobalMappingCallbacks::{on_insert_submap, on_smoother_update}`、`SubMap`、`gtsam::symbol_shorthand::X`。
- Produces: `librtk_global.so` + `extern "C" create_extension_module()`。

- [ ] **Step 1: 写配置 config_rtk_global.json**

```jsonc
{
  "rtk_global": {
    "rtk_fix_topic": "/cgi610/rtk_fix",
    "min_quality": 3,
    "max_diff_age": 15.0,
    "min_sats": 6,
    "quality_sigma_scale": [0.0, 50.0, 20.0, 5.0, 1.0],
    "sigma_floor": [0.02, 0.02, 0.05],
    "vertical_scale": 3.0,
    "robust_kernel": "huber",
    "robust_delta": 1.345,
    "T_imu_gnss": [0.0, 0.0, 0.0],
    "min_baseline": 10.0,
    "enu_origin": [],
    "fix_buffer_horizon": 60.0
  }
}
```

- [ ] **Step 2: 写模块头 rtk_global_module.hpp**

参照 `modules/mapping/gnss_global/include/glim_ext/gnss_global_module.hpp` 的结构(`#define GLIM_ROS2`、`ExtensionModuleROS2` 基类、`create_subscriptions()`、后台线程 + `ConcurrentVector`),但成员为:
```cpp
class RtkGlobal : public glim::ExtensionModuleROS2 {
public:
  RtkGlobal();                          // 读 config,建 policy/buffer/aligner,注册回调,起后台线程
  ~RtkGlobal();
  std::vector<glim::GenericTopicSubscription::Ptr> create_subscriptions() override;  // 订阅 rtk_fix_topic
private:
  void rtk_fix_callback(const gnss_msgs::msg::RtkFix::ConstSharedPtr msg);  // → RtkFixSample → buffer
  void on_insert_submap(const glim::SubMap::ConstPtr& submap);             // → 队列
  void on_smoother_update(gtsam_points::ISAM2Ext&, gtsam::NonlinearFactorGraph&, gtsam::Values&);
  void backend_task();                  // 关联→ENU→对齐→造因子→输出队列

  gnss_core::RtkFixBuffer buffer_;
  std::unique_ptr<gnss_core::RtkNoisePolicy> policy_;
  std::unique_ptr<gnss_core::FrameAligner> aligner_;
  std::unique_ptr<gnss_core::LlaToEnu> lla_to_enu_;   // 首个过门限 fix 时惰性建
  Eigen::Vector3d lever_imu_;
  double fix_buffer_horizon_;
  std::string rtk_fix_topic_;
  glim::ConcurrentVector<glim::SubMap::ConstPtr> input_submap_queue_;
  glim::ConcurrentVector<gtsam::NonlinearFactor::shared_ptr> output_factors_;
  std::atomic_bool kill_switch_;
  std::thread thread_;
  std::shared_ptr<spdlog::logger> logger_;
};
```
`backend_task()` 逻辑(spec §7.1):对每个新 submap,取 `submap->origin_frame()->stamp`,`buffer_.interpolate(stamp)`;拿到样本后,若 `lla_to_enu_` 未建则以该样本 lla 建原点(或用 config `enu_origin`);`enu = lla_to_enu_->forward(...)`;`aligner_->add(submap->T_world_origin.translation(), enu)`;若 `aligner_->initialized()`:`p_world = aligner_->T_world_enu() * enu`,`model = policy_->evaluate(sample)`,若非空则 `output_factors_.push_back(std::make_shared<gnss_core::AntennaPriorFactor>(X(submap->id), p_world, lever_imu_, model))`。`on_smoother_update` 里 drain `output_factors_` 到 `new_factors`。

- [ ] **Step 3: 写实现 rtk_global_module_ros2.cpp**

含各方法实现与:
```cpp
extern "C" glim::ExtensionModule* create_extension_module() { return new glim::RtkGlobal(); }
```

- [ ] **Step 4: 写 CMakeLists.txt**(仿 gnss_global,加 gnss_core / gnss_msgs / GeographicLib)

```cmake
cmake_minimum_required(VERSION 3.22)
project(rtk_global)
set(CMAKE_CXX_STANDARD 17)

find_package(glim REQUIRED)
find_package(GTSAM REQUIRED)
find_package(spdlog REQUIRED)
find_package(gnss_core REQUIRED)
find_package(ament_cmake_auto REQUIRED)
ament_auto_find_build_dependencies()

ament_auto_add_library(rtk_global SHARED src/glim_ext/rtk_global_module_ros2.cpp)
target_include_directories(rtk_global PRIVATE include ${GTSAM_INCLUDE_DIRS} ${glim_INCLUDE_DIRS})
target_link_libraries(rtk_global glim_ext gnss_core ${GTSAM_LIBRARIES} ${glim_LIBRARIES} spdlog::spdlog)
```
`package.xml` 加 `<depend>gnss_core</depend>` `<depend>gnss_msgs</depend>` `<depend>glim</depend>`。

- [ ] **Step 5: 构建**

Run: `cd /home/steve/glim_ws && colcon build --packages-select rtk_global`
Expected: 生成 `librtk_global.so`。

- [ ] **Step 6: 加载验证**

Run:
```bash
cd /home/steve/glim_ws && source install/setup.bash && python3 -c "
import ctypes
lib = ctypes.CDLL('install/rtk_global/lib/librtk_global.so')
lib.create_extension_module.restype = ctypes.c_void_p
assert lib.create_extension_module() != 0
print('rtk_global loads and constructs OK')"
```
Expected: 打印成功(模块能加载、`create_extension_module()` 返回非空)。

- [ ] **Step 7: Commit**

```bash
cd /home/steve/glim_ws && git add src/glim_ext/modules/mapping/rtk_global src/glim_ext/config/config_rtk_global.json && \
git commit -m "feat(rtk_global): quality-aware GNSS global constraint module"
```

---

### Task 10: pos_io(.pos 读取)

**Files:**
- Modify: `gnss_core/include/gnss_core/pos_io.hpp`
- Modify: `gnss_core/src/pos_io.cpp`
- Test: `gnss_core/test/test_pos_io.cpp`

**Interfaces:**
- Consumes: `Quality`
- Produces:
```cpp
struct PosRecord {
  double stamp;                 // unix seconds
  double lat, lon, height;
  int q;                        // RTKLIB Q: 1=fix 2=float 4=dgps 5=single
  int ns;
  Eigen::Vector3d sdne;         // sdn, sde, sdu
  double age, ratio;
};
std::vector<PosRecord> read_pos(const std::string& path);   // 跳过 % 注释行
Quality q_to_quality(int q);    // 1→FIXED 2→FLOAT 4→DGPS 5→SINGLE 其它→NONE
```

- [ ] **Step 1: 写头文件**(同上 Interfaces,加 includes)

- [ ] **Step 2: 写失败测试**

```cpp
#include <gtest/gtest.h>
#include <fstream>
#include "gnss_core/pos_io.hpp"
using namespace gnss_core;

TEST(PosIo, ParsesRtklibPos) {
  const char* path = "/tmp/test_gnss_core.pos";
  std::ofstream f(path);
  f << "% program : RTKLIB\n";
  f << "%  GPST latitude longitude height Q ns sdn sde sdu ...\n";
  f << "2026/09/03 10:23:45.000 44.50123456 90.28765432 617.123 1 38 0.012 0.011 0.030 0.0 0.0 0.0 0.8 20.5\n";
  f.close();
  auto recs = read_pos(path);
  ASSERT_EQ(recs.size(), 1u);
  EXPECT_EQ(recs[0].q, 1);
  EXPECT_NEAR(recs[0].lat, 44.50123456, 1e-8);
  EXPECT_EQ(recs[0].ns, 38);
  EXPECT_NEAR(recs[0].sdne(0), 0.012, 1e-9);
  EXPECT_NEAR(recs[0].ratio, 20.5, 1e-6);
}

TEST(PosIo, QToQuality) {
  EXPECT_EQ(q_to_quality(1), Quality::FIXED);
  EXPECT_EQ(q_to_quality(2), Quality::FLOAT);
  EXPECT_EQ(q_to_quality(5), Quality::SINGLE);
}
```

在 CMakeLists 注册 `test_pos_io`。

- [ ] **Step 3: 跑测试确认失败**

Run: `cd /home/steve/driver_ws && colcon build --packages-select gnss_core --cmake-args -DBUILD_TESTING=ON && colcon test --packages-select gnss_core --ctest-args -R test_pos_io --event-handlers console_direct+`
Expected: FAIL。

- [ ] **Step 4: 写实现 pos_io.cpp**

按 RTKLIB `.pos` 格式:注释行以 `%` 开头跳过;数据行首两列是 `YYYY/MM/DD` 与 `HH:MM:SS.sss`,合成 UTC 后转 unix 秒;其余列按 `lat lon height Q ns sdn sde sdu sdne sdeu sdun age ratio`。用 `std::istringstream` + `std::get_time` 解析日期时间。

- [ ] **Step 5: 跑测试确认通过**

Run: 同 Step 3
Expected: 2 passed。

- [ ] **Step 6: Commit**

```bash
cd /home/steve/driver_ws && git add src/gnss_core && \
git commit -m "feat(gnss_core): .pos reader"
```

---

### Task 11: trajectory_compare(分档误差统计)

**Files:**
- Modify: `gnss_core/include/gnss_core/trajectory_compare.hpp`
- Modify: `gnss_core/src/trajectory_compare.cpp`
- Test: `gnss_core/test/test_trajectory_compare.cpp`

**Interfaces:**
- Consumes: `PosRecord`(Task 10)、`Quality`、`LlaToEnu`(Task 3)
- Produces:
```cpp
struct QualityStats { int n=0; double rmse_h=0, rmse_v=0; double sigma_ratio_h=0; };
// 以 ref 为基准,按最近时间戳(容差 tol_s)配对 test,按 test 的 quality 分档统计
// rmse_*:test 相对 ref 的水平/垂直 RMSE;sigma_ratio_h:实际水平误差 / 板卡报的水平 σ 的均值
std::map<Quality, QualityStats> compare_by_quality(
    const std::vector<PosRecord>& ref, const std::vector<PosRecord>& test, double tol_s = 0.1);
```

- [ ] **Step 1: 写头文件**(同上 Interfaces)

- [ ] **Step 2: 写失败测试**

```cpp
#include <gtest/gtest.h>
#include "gnss_core/trajectory_compare.hpp"
using namespace gnss_core;

static PosRecord rec(double t, double lat, double lon, double h, int q, double sd) {
  PosRecord r{}; r.stamp=t; r.lat=lat; r.lon=lon; r.height=h; r.q=q;
  r.sdne = {sd, sd, sd}; return r;
}

TEST(TrajCompare, PerfectMatchZeroRmse) {
  std::vector<PosRecord> ref = {rec(100, 44.5, 90.28, 617, 1, 0.01)};
  std::vector<PosRecord> test = {rec(100, 44.5, 90.28, 617, 1, 0.01)};
  auto s = compare_by_quality(ref, test);
  ASSERT_EQ(s.count(Quality::FIXED), 1u);
  EXPECT_EQ(s[Quality::FIXED].n, 1);
  EXPECT_NEAR(s[Quality::FIXED].rmse_h, 0.0, 1e-6);
}

TEST(TrajCompare, KnownHorizontalOffset) {
  // test 相对 ref 北偏 ~1m
  const double dlat = 1.0 / 111320.0;
  std::vector<PosRecord> ref = {rec(100, 44.5, 90.28, 617, 3, 0.1)};
  std::vector<PosRecord> test = {rec(100, 44.5 + dlat, 90.28, 617, 3, 0.1)};
  auto s = compare_by_quality(ref, test);
  ASSERT_EQ(s.count(Quality::FLOAT), 1u);
  EXPECT_NEAR(s[Quality::FLOAT].rmse_h, 1.0, 0.05);
  EXPECT_NEAR(s[Quality::FLOAT].sigma_ratio_h, 10.0, 1.0);   // 1m 实际 / 0.1m σ ≈ 10
}

TEST(TrajCompare, UnpairedBeyondToleranceSkipped) {
  std::vector<PosRecord> ref = {rec(100, 44.5, 90.28, 617, 1, 0.01)};
  std::vector<PosRecord> test = {rec(102, 44.5, 90.28, 617, 1, 0.01)};  // 2s 差
  auto s = compare_by_quality(ref, test, 0.1);
  EXPECT_TRUE(s.empty());
}
```

在 CMakeLists 注册 `test_trajectory_compare`。

- [ ] **Step 3: 跑测试确认失败**

Run: `cd /home/steve/driver_ws && colcon build --packages-select gnss_core --cmake-args -DBUILD_TESTING=ON && colcon test --packages-select gnss_core --ctest-args -R test_trajectory_compare --event-handlers console_direct+`
Expected: FAIL。

- [ ] **Step 4: 写实现 trajectory_compare.cpp**

对每个 test 记录,在 ref 中二分找最近 stamp;若 |dt|>tol_s 跳过。以配对首个 ref 的 lla 为 ENU 原点建 `LlaToEnu`,把 ref/test 都转 ENU 求差;水平误差 `hypot(dE,dN)`、垂直 `|dU|`。按 `q_to_quality(test.q)` 累加,末尾算 RMSE 与 `mean(实际水平误差 / test.sdne.head<2>().norm())`。

- [ ] **Step 5: 跑测试确认通过**

Run: 同 Step 3
Expected: 3 passed。

- [ ] **Step 6: Commit**

```bash
cd /home/steve/driver_ws && git add src/gnss_core && \
git commit -m "feat(gnss_core): trajectory comparison by quality tier"
```

---

### Task 12: 系数标定工具 + 导出脚本

**Files:**
- Create: `gnss_core/tools/calibrate_sigma_scale.cpp`
- Modify: `gnss_core/CMakeLists.txt`(加 `add_executable`)
- Create: `gnss_core/tools/export_bag_to_pos.py`(rtk-monitor 既有录包 → .pos,供轨迹 1–3)
- Create: `gnss_core/tools/README.md`

**Interfaces:**
- Consumes: `read_pos`、`compare_by_quality`(Task 10/11)
- Produces: 可执行 `calibrate_sigma_scale <ref.pos> <test.pos> [tol_s]`,打印各质量档的 n / rmse_h / rmse_v / sigma_ratio_h,并给出建议的 `quality_sigma_scale`(= 各档 sigma_ratio_h,归一到 FIXED=1)。

- [ ] **Step 1: 写 calibrate_sigma_scale.cpp**

```cpp
#include <iostream>
#include "gnss_core/pos_io.hpp"
#include "gnss_core/trajectory_compare.hpp"
using namespace gnss_core;

int main(int argc, char** argv) {
  if (argc < 3) { std::cerr << "usage: calibrate_sigma_scale <ref.pos> <test.pos> [tol_s]\n"; return 1; }
  const double tol = (argc > 3) ? std::stod(argv[3]) : 0.1;
  auto ref = read_pos(argv[1]);
  auto test = read_pos(argv[2]);
  auto stats = compare_by_quality(ref, test, tol);
  const char* names[] = {"NONE","SINGLE","DGPS","FLOAT","FIXED"};
  double fixed_ratio = 0.0;
  for (auto& [q, s] : stats) if (q == Quality::FIXED) fixed_ratio = s.sigma_ratio_h;
  std::cout << "quality  n   rmse_h(m)  rmse_v(m)  sigma_ratio_h\n";
  for (auto& [q, s] : stats)
    std::cout << names[static_cast<int>(q)] << "  " << s.n << "  "
              << s.rmse_h << "  " << s.rmse_v << "  " << s.sigma_ratio_h << "\n";
  std::cout << "\nsuggested quality_sigma_scale (normalized to FIXED=1):\n";
  for (auto& [q, s] : stats)
    std::cout << "  " << names[static_cast<int>(q)] << " = "
              << (fixed_ratio > 0 ? s.sigma_ratio_h / fixed_ratio : s.sigma_ratio_h) << "\n";
  return 0;
}
```
CMakeLists 加:
```cmake
add_executable(calibrate_sigma_scale tools/calibrate_sigma_scale.cpp)
target_link_libraries(calibrate_sigma_scale gnss_core)
install(TARGETS calibrate_sigma_scale DESTINATION lib/${PROJECT_NAME})
```

- [ ] **Step 2: 写 export_bag_to_pos.py**

读 rtk-monitor 既有录包(SQLite `data/*.db` 的 epochs 表,或既有 .pos)导出为标准 `.pos`(每源一个文件),列顺序符合 Task 10 的解析。含 `--src {can,gpchc,rtkrcv}` 与 `--out` 参数。

- [ ] **Step 3: 构建工具**

Run: `cd /home/steve/driver_ws && colcon build --packages-select gnss_core`
Expected: 生成 `calibrate_sigma_scale` 可执行。

- [ ] **Step 4: 端到端标定(有数据时)**

Run:
```bash
# 用 rnx2rtkp 后处理输出作 ref,rtk-monitor 导出的 rtkrcv.pos 作 test(示例)
./install/gnss_core/lib/gnss_core/calibrate_sigma_scale ref.pos rtkrcv.pos
```
Expected: 打印分档统计与建议的 `quality_sigma_scale`。**若无成对数据,则用两条合成 .pos(已知偏移)验证工具本身正确,并在 README 记录待现场数据回来后重跑。**

- [ ] **Step 5: 写 README.md**

记录:工具用途、`.pos` 数据从哪来(rnx2rtkp / export_bag_to_pos.py)、如何把标定出的系数填回 `config_rtk_global.json` 的 `quality_sigma_scale`(spec §9.2 闭环)、RTKPLOT 叠加多条 `.pos` 做可视化对比的命令。

- [ ] **Step 6: Commit**

```bash
cd /home/steve/driver_ws && git add src/gnss_core/tools src/gnss_core/CMakeLists.txt && \
git commit -m "feat(gnss_core): sigma-scale calibration tool + bag-to-pos export"
```

---

## 依赖顺序

Task 1(gnss_msgs)→ Task 2(core 骨架)→ Task 3–7(core 算法单元,可并行但都依赖 2)→ Task 8(驱动,依赖 1)→ Task 9(模块,依赖 3–7 + 1)→ Task 10 → 11 → 12(工具链,依赖 10/11)。

## 验收(轮 1 完成标志)

- `gnss_msgs` / `gnss_core` / `rtk_global` 三包在 aarch64 上 `colcon build` 通过
- `gnss_core` 全部 gtest 通过(types/geodetic/buffer/policy/aligner/factor/pos/compare),含 AntennaPriorFactor 的 Jacobian 数值校验
- `librtk_global.so` 可被加载、`create_extension_module()` 返回非空
- `gnss_CGI610` 增发 `~/rtk_fix`,映射函数测试通过
- `calibrate_sigma_scale` 能对成对 `.pos` 产出分档统计与建议系数(spec §9 闭环)

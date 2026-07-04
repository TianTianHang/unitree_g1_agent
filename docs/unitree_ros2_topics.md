# Unitree G1/H1 机器人 ROS2 Topics 文档

## 目录
- [项目概述](#项目概述)
- [机器人配置](#机器人配置)
- [ROS2 Topics 完整列表](#ros2-topics-完整列表)
- [消息类型定义](#消息类型定义)
- [API功能说明](#api功能说明)
- [代码示例](#代码示例)
- [使用指南](#使用指南)

## 项目概述

本项目为 Unitree G1 和 H1 系列人形机器人提供完整的 ROS2 接口，基于 CycloneDDS 实现高性能通信。

### 核心包
- `unitree_api` - API 通信接口
- `unitree_go` - Go 系列机器人消息定义
- `unitree_hg` - HG 系列（包括 g1 和 h1）机器人消息定义
- `example` - 示例代码

## 机器人配置

### G1 机器人（29/35 自由度）
- **腿部**（12关节）：左右髋关节俯仰/横滚/偏航、膝关节、踝关节俯仰/横滚
- **腰部**（3关节）：偏航、横滚、俯仰（23dof/29dof 版本部分锁定）
- **手臂**（14关节）：左右肩关节俯仰/横滚/偏航、肘关节、腕关节俯仰/横滚/偏航

### H1_2 机器人（27 自由度）
- **腿部**（12关节）：与 G1 相同
- **腰部**（1关节）：偏航
- **手臂**（14关节）：与 G1 相同

## ROS2 Topics 完整列表

### 1. 低级别控制 Topics

| Topic 名称 | 消息类型 | 方向 | 频率 | 用途 |
|-----------|----------|------|------|------|
| `lowstate` | `unitree_hg::msg::LowState` | 订阅 | 500Hz | 机器人底层状态（高频） |
| `lf/lowstate` | `unitree_hg::msg::LowState` | 订阅 | ~50Hz | 机器人底层状态（低频） |
| `/lowcmd` | `unitree_hg::msg::LowCmd` | 发布 | 500Hz | 电机控制命令（根命名空间） |
| `lowcmd` | `unitree_hg::msg::LowCmd` | 发布 | 500Hz | 电机控制命令（无前缀） |
| `/arm_sdk` | `unitree_hg::msg::LowCmd` | 发布 | 50Hz | 手臂 SDK 控制命令 |

### 2. 传感器状态 Topics

| Topic 名称 | 消息类型 | 方向 | 频率 | 用途 |
|-----------|----------|------|------|------|
| `secondary_imu` | `unitree_hg::msg::IMUState` | 订阅 | 500Hz | 躯干 IMU 数据 |

### 3. 手部控制 Topics (Dex3)

| Topic 名称 | 消息类型 | 方向 | 频率 | 用途 |
|-----------|----------|------|------|------|
| `/dex3/left/cmd` | `unitree_hg::msg::HandCmd` | 发布 | - | 左手控制命令 |
| `/dex3/right/cmd` | `unitree_hg::msg::HandCmd` | 发布 | - | 右手控制命令 |
| `/lf/dex3/left/state` | `unitree_hg::msg::HandState` | 订阅 | - | 左手状态反馈 |
| `/lf/dex3/right/state` | `unitree_hg::msg::HandState` | 订阅 | - | 右手状态反馈 |

### 4. API 请求/响应 Topics

| Topic 名称 | 消息类型 | 方向 | 用途 |
|-----------|----------|------|------|
| `/api/sport/request` | `unitree_api::msg::Request` | 发布 | 运动控制 API 请求 |
| `/api/sport/response` | `unitree_api::msg::Response` | 订阅 | 运动控制 API 响应 |
| `/api/arm/request` | `unitree_api::msg::Request` | 发布 | 手臂动作 API 请求 |
| `/api/arm/response` | `unitree_api::msg::Response` | 订阅 | 手臂动作 API 响应 |
| `/api/voice/request` | `unitree_api::msg::Request` | 发布 | 语音/音频 API 请求 |
| `/api/voice/response` | `unitree_api::msg::Response` | 订阅 | 语音/音频 API 响应 |
| `/api/motion_switcher/request` | `unitree_api::msg::Request` | 发布 | 运动切换 API 请求 |
| `/api/motion_switcher/response` | `unitree_api::msg::Response` | 订阅 | 运动切换 API 响应 |

## 消息类型定义

### LowState 消息

机器人底层状态消息，包含完整的传感器和状态数据。

```cpp
// 消息类型: unitree_hg::msg::LowState
// 频率: 500Hz

// 主要字段:
- quaternion[4]         // 姿态四元数 (w, x, y, z)
- gyroscope[3]          // 陀螺仪数据 (rad/s)
- accelerometer[3]      // 加速度计数据 (m/s²)
- rpy[3]                // 欧拉角 (roll, pitch, yaw)
- motor_state[35]       // 35 个电机状态
  - q                   // 关节位置
  - dq                  // 关节速度
  - ddq                 // 关节加速度
  - tau_est             // 估计扭矩
  - temperature         // 电机温度
  - q_raw               // 原始位置
  - dq_raw              // 原始速度
  - ddq_raw             // 原始加速度
  - tau_raw             // 原始扭矩
- remote_controller[40] // 无线遥控器数据
- mode_info             // 机器人模式信息
```

### LowCmd 消息

机器人底层控制命令消息。

```cpp
// 消息类型: unitree_hg::msg::LowCmd
// 频率: 500Hz

// 主要字段:
- motor_cmd[35]         // 35 个电机命令
  - q                   // 目标位置
  - dq                  // 目标速度
  - kp                  // 位置增益
  - kd                  // 速度增益
  - tau                 // 前馈扭矩
- mode                  // 模式设置 (PR/AB 模式)
- crc                   // CRC 校验值
```

### IMUState 消息

IMU 传感器状态消息。

```cpp
// 消息类型: unitree_hg::msg::IMUState
// 频率: 500Hz

// 主要字段:
- quaternion[4]         // 姿态四元数
- gyroscope[3]          // 陀螺仪数据
- accelerometer[3]      // 加速度计数据
- rpy[3]                // 欧拉角
- temperature           // 温度
```

### HandState 消息

手部状态反馈消息。

```cpp
// 消息类型: unitree_hg::msg::HandState

// 主要字段:
- motor_state[7]        // 7 个电机状态
- contact[9]            // 9 个压力传感器状态
- imu                   // 手部 IMU 状态
- battery               // 电源信息
  - voltage             // 电压
  - current             // 电流
- error_code            // 错误码
```

### HandCmd 消息

手部控制命令消息。

```cpp
// 消息类型: unitree_hg::msg::HandCmd

// 主要字段:
- motor_cmd[7]          // 7 个电机控制命令
- control_mode          // 控制模式
```

### Request/Response 消息

API 通信消息。

```cpp
// 消息类型: unitree_api::msg::Request
// 消息类型: unitree_api::msg::Response

// Request 主要字段:
- sequence_id           // 序列号
- api_id                // API 标识
- parameter             // 参数 (二进制数据)

// Response 主要字段:
- sequence_id           // 序列号
- api_id                // API 标识
- code                  // 状态码
- parameter             // 返回数据 (二进制数据)
```

## API 功能说明

### 运动控制 API (`/api/sport/`)

#### 基础控制
- `GetState()` - 获取机器人状态
- `SetMode(mode)` - 设置机器人模式
- `GetSwitch()` - 获取开关状态
- `SwitchGet()` - 获取切换状态
- `GetActuatorState()` - 获取执行器状态

#### 高级动作
- `Damp()` - 阻尼模式
- `Start()` - 开始运动
- `Squat()` - 下蹲
- `Sit()` - 坐下
- `StandUp()` - 站立
- `ZeroTorque()` - 零力矩模式
- `StopMove()` - 停止移动
- `HighStand()` / `LowStand()` - 高/低站立
- `BalanceStand()` - 平衡站立
- `ContinuousGait()` - 连续步态
- `Move(vx, vy, vyaw)` - 移动控制
- `MoveTo(target)` - 移动到目标
- `SwitchGait(gait_type)` - 切换步态

#### 交互动作
- `WaveHand()` - 挥手动作
- `ShakeHand()` - 握手动作

### 手臂动作 API (`/api/arm/`)

- `MoveTo(joint_pos)` - 移动手臂到目标位置
- `GetArmState()` - 获取手臂状态
- `SetArmStiffness(kp, kd)` - 设置手臂刚度
- `ResetArm()` - 复位手臂

### 音频控制 API (`/api/voice/`)

- `TtsMaker(text, speaker_id)` - 文本转语音
- `GetVolume()` - 获取音量
- `SetVolume(volume)` - 设置音量
- `PlayStream(audio_data)` - 播放音频流
- `PlayStop()` - 停止播放
- `LedControl(r, g, b)` - LED 控制

### 运动切换 API (`/api/motion_switcher/`)

- `CheckMode()` - 检查当前模式
- `SelectMode(mode)` - 选择模式
- `ReleaseMode()` - 释放模式
- `SetSilent(silent)` - 设置静音模式
- `GetSilent()` - 获取静音状态

## 代码示例

### 1. 低级别控制示例

```cpp
#include <rclcpp/rclcpp.hpp>
#include <unitree_hg/msg/LowCmd.hpp>
#include <unitree_hg/msg/LowState.hpp>

class LowLevelController : public rclcpp::Node {
public:
    LowLevelController() : Node("low_level_controller") {
        // 创建发布者和订阅者
        lowcmd_pub_ = this->create_publisher<unitree_hg::msg::LowCmd>("lowcmd", 10);
        lowstate_sub_ = this->create_subscription<unitree_hg::msg::LowState>(
            "lowstate", 10, std::bind(&LowLevelController::stateCallback, this, std::placeholders::_1));
        
        // 初始化控制命令
        cmd_msg_ = std::make_shared<unitree_hg::msg::LowCmd>();
        
        // 创建定时器（500Hz）
        timer_ = this->create_wall_timer(
            std::chrono::milliseconds(2),
            std::bind(&LowLevelController::controlLoop, this));
    }

private:
    void stateCallback(const unitree_hg::msg::LowState::SharedPtr msg) {
        // 机器人状态回调
        current_state_ = msg;
    }

    void controlLoop() {
        if (!current_state_) return;
        
        // 示例：设置关节位置控制
        for (size_t i = 0; i < cmd_msg_->motor_cmd.size(); ++i) {
            cmd_msg_->motor_cmd[i].q = current_state_->motor_state[i].q;  // 保持当前位置
            cmd_msg_->motor_cmd[i].kp = 20.0;  // 位置增益
            cmd_msg_->motor_cmd[i].kd = 0.5;   // 速度增益
        }
        
        // 发布控制命令
        lowcmd_pub_->publish(*cmd_msg_);
    }

    rclcpp::Publisher<unitree_hg::msg::LowCmd>::SharedPtr lowcmd_pub_;
    rclcpp::Subscription<unitree_hg::msg::LowState>::SharedPtr lowstate_sub_;
    rclcpp::TimerBase::SharedPtr timer_;
    unitree_hg::msg::LowState::SharedPtr current_state_;
    std::shared_ptr<unitree_hg::msg::LowCmd> cmd_msg_;
};

int main(int argc, char** argv) {
    rclcpp::init(argc, argv);
    rclcpp::spin(std::make_shared<LowLevelController>());
    rclcpp::shutdown();
    return 0;
}
```

### 2. 高级别运动控制示例

```cpp
#include <rclcpp/rclcpp.hpp>
#include <unitree_api/msg/Request.hpp>
#include <unitree_api/msg/Response.hpp>

class HighLevelController : public rclcpp::Node {
public:
    HighLevelController() : Node("high_level_controller") {
        // 创建发布者和订阅者
        request_pub_ = this->create_publisher<unitree_api::msg::Request>("/api/sport/request", 10);
        response_sub_ = this->create_subscription<unitree_api::msg::Response>(
            "/api/sport/response", 10, std::bind(&HighLevelController::responseCallback, this, std::placeholders::_1));
        
        sequence_id_ = 0;
    }

    void standUp() {
        auto request = std::make_shared<unitree_api::msg::Request>();
        request->sequence_id = sequence_id_++;
        request->api_id = ApiID::StandUp;
        
        // 构建 protobuf 数据
        sport_api::StandUpRequest stand_up_req;
        request->parameter = stand_up_req.SerializeAsString();
        
        request_pub_->publish(*request);
    }

    void move(double vx, double vy, double vyaw) {
        auto request = std::make_shared<unitree_api::msg::Request>();
        request->sequence_id = sequence_id_++;
        request->api_id = ApiID::Move;
        
        // 构建 protobuf 数据
        sport_api::MoveRequest move_req;
        move_req.set_vx(vx);
        move_req.set_vy(vy);
        move_req.set_vyaw(vyaw);
        
        request->parameter = move_req.SerializeAsString();
        
        request_pub_->publish(*request);
    }

    void waveHand() {
        auto request = std::make_shared<unitree_api::msg::Request>();
        request->sequence_id = sequence_id_++;
        request->api_id = ApiID::WaveHand;
        
        request_pub_->publish(*request);
    }

private:
    void responseCallback(const unitree_api::msg::Response::SharedPtr msg) {
        RCLCPP_INFO(this->get_logger(), "Response received: sequence_id=%d, code=%d",
                    msg->sequence_id, msg->code);
    }

    rclcpp::Publisher<unitree_api::msg::Request>::SharedPtr request_pub_;
    rclcpp::Subscription<unitree_api::msg::Response>::SharedPtr response_sub_;
    int sequence_id_;
};
```

### 3. 手部控制示例

```cpp
#include <rclcpp/rclcpp.hpp>
#include <unitree_hg/msg/HandCmd.hpp>
#include <unitree_hg/msg/HandState.hpp>

class HandController : public rclcpp::Node {
public:
    HandController() : Node("hand_controller") {
        left_hand_cmd_pub_ = this->create_publisher<unitree_hg::msg::HandCmd>("/dex3/left/cmd", 10);
        right_hand_cmd_pub_ = this->create_publisher<unitree_hg::msg::HandCmd>("/dex3/right/cmd", 10);
        
        left_hand_state_sub_ = this->create_subscription<unitree_hg::msg::HandState>(
            "/lf/dex3/left/state", 10, std::bind(&HandController::leftHandStateCallback, this, std::placeholders::_1));
        
        right_hand_state_sub_ = this->create_subscription<unitree_hg::msg::HandState>(
            "/lf/dex3/right/state", 10, std::bind(&HandController::rightHandStateCallback, this, std::placeholders::_1));
    }

    void graspLeftHand() {
        auto cmd = std::make_shared<unitree_hg::msg::HandCmd>();
        
        // 设置抓握姿势
        cmd->motor_cmd[0].q = 0.0;   // 拇指
        cmd->motor_cmd[1].q = 0.0;   // 食指
        cmd->motor_cmd[2].q = 0.0;   // 中指
        cmd->motor_cmd[3].q = 0.0;   // 无名指
        cmd->motor_cmd[4].q = 0.0;   // 小指
        cmd->motor_cmd[5].q = 0.0;   // 腕部俯仰
        cmd->motor_cmd[6].q = 0.0;   // 腕部偏航
        
        for (auto& motor : cmd->motor_cmd) {
            motor.kp = 30.0;
            motor.kd = 1.0;
        }
        
        left_hand_cmd_pub_->publish(*cmd);
    }

    void releaseLeftHand() {
        auto cmd = std::make_shared<unitree_hg::msg::HandCmd>();
        
        // 设置放松姿势
        for (auto& motor : cmd->motor_cmd) {
            motor.q = 1.0;  // 完全张开
            motor.kp = 20.0;
            motor.kd = 0.5;
        }
        
        left_hand_cmd_pub_->publish(*cmd);
    }

private:
    void leftHandStateCallback(const unitree_hg::msg::HandState::SharedPtr msg) {
        RCLCPP_DEBUG(this->get_logger(), "Left hand state received");
    }

    void rightHandStateCallback(const unitree_hg::msg::HandState::SharedPtr msg) {
        RCLCPP_DEBUG(this->get_logger(), "Right hand state received");
    }

    rclcpp::Publisher<unitree_hg::msg::HandCmd>::SharedPtr left_hand_cmd_pub_;
    rclcpp::Publisher<unitree_hg::msg::HandCmd>::SharedPtr right_hand_cmd_pub_;
    rclcpp::Subscription<unitree_hg::msg::HandState>::SharedPtr left_hand_state_sub_;
    rclcpp::Subscription<unitree_hg::msg::HandState>::SharedPtr right_hand_state_sub_;
};
```

### 4. Python 示例

```python
import rclpy
from rclpy.node import Node
from unitree_hg.msg import LowCmd, LowState

class LowLevelController(Node):
    def __init__(self):
        super().__init__('low_level_controller')
        
        self.lowcmd_pub = self.create_publisher(LowCmd, 'lowcmd', 10)
        self.lowstate_sub = self.create_subscription(
            LowState, 'lowstate', self.state_callback, 10)
        
        self.current_state = None
        self.timer = self.create_timer(0.002, self.control_loop)  # 500Hz
    
    def state_callback(self, msg):
        self.current_state = msg
    
    def control_loop(self):
        if self.current_state is None:
            return
        
        cmd = LowCmd()
        
        # 示例：保持当前位置
        for i in range(len(cmd.motor_cmd)):
            cmd.motor_cmd[i].q = self.current_state.motor_state[i].q
            cmd.motor_cmd[i].kp = 20.0
            cmd.motor_cmd[i].kd = 0.5
        
        self.lowcmd_pub.publish(cmd)

def main():
    rclpy.init()
    node = LowLevelController()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
```

## 使用指南

### 环境配置

1. 安装依赖
```bash
# 配置 CycloneDDS
source setup.sh

# 或使用本地配置
source setup_local.sh
```

2. 构建项目
```bash
cd cyclonedds_ws
colcon build --symlink-install
source install/setup.bash
```

### 启动机器人

```bash
# 启动低级别控制
ros2 run example g1_low_level_example

# 启动高级别控制
ros2 run example loco_client_example

# 启动手部控制
ros2 run example g1_dex3_example
```

### 监控 Topics

```bash
# 查看所有 topics
ros2 topic list

# 查看机器人状态
ros2 topic echo /lowstate

# 查看低频状态
ros2 topic echo /lf/lowstate

# 查看 IMU 数据
ros2 topic echo /secondary_imu

# 查看手部状态
ros2 topic echo /lf/dex3/left/state

# 查看运动控制响应
ros2 topic echo /api/sport/response
```

### 发布控制命令

```bash
# 发送电机命令（需要发布 LowCmd 消息）
ros2 topic pub /lowcmd unitree_hg/msg/LowCmd '{...}' --once

# 发送运动控制请求（需要发布 Request 消息）
ros2 topic pub /api/sport/request unitree_api/msg/Request '{...}' --once
```

### 故障排除

1. **连接问题**
   - 检查网络连接
   - 确认 CycloneDDS 配置正确
   - 检查防火墙设置

2. **通信延迟**
   - 确认 DDS 配置（`cyclonedds.xml`）
   - 检查网络带宽
   - 减少不必要的订阅

3. **控制不稳定**
   - 调整电机增益（kp, kd）
   - 检查传感器数据
   - 确认控制频率（500Hz）

### 最佳实践

1. **低级别控制**
   - 保持 500Hz 控制频率
   - 使用 CRC 校验确保数据完整性
   - 监控电机温度和扭矩

2. **高级别控制**
   - 使用 API 请求/响应机制
   - 处理序列号和超时
   - 检查返回状态码

3. **安全措施**
   - 实现紧急停止功能
   - 设置关节位置限制
   - 监控错误状态

4. **性能优化**
   - 使用共享指针减少拷贝
   - 批量处理传感器数据
   - 异步处理耗时操作

## 附录

### A. 关节映射

| 关节索引 | G1 名称 | H1 名称 |
|----------|---------|---------|
| 0-5 | 左腿（髋俯仰、横滚、偏航、膝、踝俯仰、踝横滚） | 左腿 |
| 6-11 | 右腿 | 右腿 |
| 12-14 | 腰部（偏航、横滚、俯仰） | 腰部偏航 |
| 15-20 | 左臂（肩俯仰、横滚、偏航、肘、腕俯仰、腕偏航） | 左臂 |
| 21-26 | 右臂 | 右臂 |
| 27-34 | 额外关节（35dof 版本） | - |

### B. 错误码

| 错误码 | 含义 |
|--------|------|
| 0 | 成功 |
| 1 | 未知错误 |
| 2 | 参数错误 |
| 3 | 超时 |
| 4 | 运动模式错误 |
| 5 | 安全错误 |
| 6 | 通信错误 |

### C. 频率要求

| Topic | 推荐频率 | 最小频率 |
|-------|----------|----------|
| lowcmd | 500Hz | 100Hz |
| lowstate | 500Hz | 100Hz |
| /arm_sdk | 50Hz | 20Hz |
| /api/sport/request | 按需 | - |
| /dex3/*/cmd | 100Hz | 50Hz |

### D. 参考资料

- Unitree 官方文档: https://www.unitree.com/
- CycloneDDS 文档: https://docs.cyclonedds.io/
- ROS2 文档: https://docs.ros.org/

---

**文档版本**: 1.0
**最后更新**: 2026-07-04
**适用机器人**: Unitree G1/H1 系列
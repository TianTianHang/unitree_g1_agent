# Unitree SDK2 高层 API 接口完整文档

本文档详细介绍了 Unitree SDK2 的所有高层 API 接口，包括运控服务、SLAM 导航服务、音量灯光服务等。

## 文档概述

**适用范围**：
- Go2 Edu 型号，软件版本 ≥ V1.1.6
- G1/H1 人形机器人系列

**SDK 仓库**：
- C++ 版本：https://github.com/unitreerobotics/unitree_sdk2
- Python 版本：https://github.com/unitreerobotics/unitree_sdk2_python

**官方文档**：
- Go2 SDK 开发指南：https://support.unitree.com/home/zh/developer

---

## 一、运控服务接口 V2.0

运控服务的高层接口分为两个部分：
- **高层控制接口**：通过调用 SDK 的 `SportClient`，给 Go2 发送模式切换、速度控制等运动指令
- **高层状态接口**：通过订阅 SDK 中的 `sportmodestate` 消息，获取 Go2 的位置、速度、姿态、当前运动模式等运动状态

### 1.1 使用示例

```cpp
#include <unitree/robot/go2/sport/sport_client.hpp>

int main(int argc, char **argv)
{
    // 初始化通信通道
    unitree::robot::ChannelFactory::Instance()->Init(0, argv[1]);
    
    // 创建 sport client 对象
    unitree::robot::go2::SportClient sport_client;
    sport_client.SetTimeout(10.0f);  // 设置超时时间
    sport_client.Init();
    
    // 调用运动控制接口
    sport_client.Sit();        // 坐下
    sleep(3);
    sport_client.RiseSit();    // 站起
    sleep(3);
    
    return 0;
}
```

### 1.2 高层运动控制接口

#### 基本控制接口

##### 1. Damp() - 进入阻尼状态
```cpp
int32_t Damp()
```
- **功能**：所有电机关节停止运动并进入阻尼状态
- **参数**：无
- **返回值**：成功返回 0，否则返回错误码
- **备注**：该模式具有最高优先级，用于突发情况下的急停

##### 2. BalanceStand() - 平衡站立
```cpp
int32_t BalanceStand()
```
- **功能**：解除关节电机锁定，切换到平衡站立模式
- **参数**：无
- **返回值**：成功返回 0，否则返回错误码
- **备注**：机身姿态和高度会始终保持平衡，不受地形影响

##### 3. StopMove() - 停止运动
```cpp
int32_t StopMove()
```
- **功能**：停下当前动作，将绝大多数指令恢复成默认值
- **参数**：无
- **返回值**：成功返回 0，否则返回错误码

##### 4. StandUp() - 站高
```cpp
int32_t StandUp()
```
- **功能**：关节锁定，站高
- **参数**：无
- **返回值**：成功返回 0，否则返回错误码
- **备注**：
  - 默认站立高度为 0.33m
  - 锁定姿态容易导致电机过热，请及时解锁

##### 5. StandDown() - 站低
```cpp
int32_t StandDown()
```
- **功能**：关节锁定，站低（趴下）
- **参数**：无
- **返回值**：成功返回 0，否则返回错误码

##### 6. RecoveryStand() - 恢复站立
```cpp
int32_t RecoveryStand()
```
- **功能**：从翻倒或趴下状态恢复至平衡站立状态
- **参数**：无
- **返回值**：成功返回 0，否则返回错误码
- **备注**：不论是否翻倒，都会恢复至站立

#### 姿态与速度控制接口

##### 7. Euler() - 姿态控制
```cpp
int32_t Euler(float roll, float pitch, float yaw)
```
- **功能**：设置站立和行走时的机体姿态角
- **参数**：
  - `roll`：横滚角，取值范围 [-0.75~0.75] (rad)
  - `pitch`：俯仰角，取值范围 [-0.75~0.75] (rad)
  - `yaw`：偏航角，取值范围 [-0.6~0.6] (rad)
- **返回值**：成功返回 0，否则返回错误码
- **备注**：欧拉角采用绕机体相对轴和 z-y-x 旋转顺序

##### 8. Move() - 移动控制
```cpp
int32_t Move(float vx, float vy, float vyaw)
```
- **功能**：控制移动速度
- **参数**：
  - `vx`：X 方向速度，取值范围 [-2.5~3.8] (m/s)
  - `vy`：Y 方向速度，取值范围 [-1.0~1.0] (m/s)
  - `vyaw`：偏航角速度，取值范围 [-4~4] (rad/s)
- **返回值**：成功返回 0，否则返回错误码
- **备注**：
  - 设定的速度为机体坐标系下的速度
  - 运控部分不会对 Move 指令进行滤波
  - 最新的 Move 指令会维持 1s
  - 建议自行加滤波，不使用时发送 Move(0,0,0) 或 StopMove()

#### 特殊动作接口

##### 9. Sit() - 坐下
```cpp
int32_t Sit()
```
- **功能**：特殊动作，机器狗坐下
- **参数**：无
- **返回值**：成功返回 0，否则返回错误码
- **备注**：需要在上一个动作执行完毕后再执行

##### 10. RiseSit() - 站起
```cpp
int32_t RiseSit()
```
- **功能**：从坐下状态恢复到平衡站立
- **参数**：无
- **返回值**：成功返回 0，否则返回错误码

##### 11. SpeedLevel() - 设置速度档位
```cpp
int32_t SpeedLevel(int level)
```
- **功能**：设置速度档位
- **参数**：
  - `level`：-1 为慢速，0 为正常，1 为快速
- **返回值**：成功返回 0，否则返回错误码

##### 12. Hello() - 打招呼
```cpp
int32_t Hello()
```
- **功能**：打招呼动作
- **参数**：无
- **返回值**：成功返回 0，否则返回错误码

##### 13. Stretch() - 伸懒腰
```cpp
int32_t Stretch()
```
- **功能**：伸懒腰动作
- **参数**：无
- **返回值**：成功返回 0，否则返回错误码

##### 14. Content() - 开心
```cpp
int32_t Content()
```
- **功能**：开心动作
- **参数**：无
- **返回值**：成功返回 0，否则返回错误码

##### 15. Heart() - 比心
```cpp
int32_t Heart()
```
- **功能**：比心动作
- **参数**：无
- **返回值**：成功返回 0，否则返回错误码

##### 16. Pose() - 摆姿势
```cpp
int32_t Pose(bool flag)
```
- **功能**：摆姿势
- **参数**：
  - `flag`：true 为摆姿势，false 为恢复
- **返回值**：成功返回 0，否则返回错误码

##### 17. Scrape() - 拜年作揖
```cpp
int32_t Scrape()
```
- **功能**：拜年作揖动作
- **参数**：无
- **返回值**：成功返回 0，否则返回错误码

#### 高难度动作接口

##### 18. FrontFlip() - 前空翻
```cpp
int32_t FrontFlip()
```
- **功能**：前空翻
- **参数**：无
- **返回值**：成功返回 0，否则返回错误码
- **⚠️ 警告**：
  - 该动作存在一定危险性，请注意与他人保持安全距离
  - 可能会加速硬件损伤，减少使用寿命
  - 谨慎使用

##### 19. FrontJump() - 前跳
```cpp
int32_t FrontJump()
```
- **功能**：前跳动作
- **参数**：无
- **返回值**：成功返回 0，否则返回错误码

##### 20. FrontPounce() - 向前扑人
```cpp
int32_t FrontPounce()
```
- **功能**：向前扑人动作
- **参数**：无
- **返回值**：成功返回 0，否则返回错误码

##### 21. Dance1() - 舞蹈段落1
```cpp
int32_t Dance1()
```
- **功能**：舞蹈段落 1
- **参数**：无
- **返回值**：成功返回 0，否则返回错误码

##### 22. Dance2() - 舞蹈段落2
```cpp
int32_t Dance2()
```
- **功能**：舞蹈段落 2
- **参数**：无
- **返回值**：成功返回 0，否则返回错误码

##### 23. HandStand() - 倒立行走
```cpp
int32_t HandStand(bool flag)
```
- **功能**：进入倒立模式
- **参数**：
  - `flag`：true 为开启，false 为关闭
- **返回值**：成功返回 0，否则返回错误码
- **备注**：
  - 需要在可移动状态下才能进入
  - 建议先发送 BalanceStand() 确保可切入
  - 该步态电机容易过热，请自行把控业务逻辑

##### 24. LeftFlip() - 左空翻
```cpp
int32_t LeftFlip()
```
- **功能**：单次左空翻，结束后自动进入灵动模式
- **参数**：无
- **返回值**：成功返回 0，否则返回错误码
- **备注**：需要在非运动状态下进入
- **⚠️ 警告**：
  - 该动作存在一定危险性
  - 可能会加速硬件损伤

##### 25. BackFlip() - 后空翻
```cpp
int32_t BackFlip()
```
- **功能**：单次后空翻，结束后自动进入灵动模式
- **参数**：无
- **返回值**：成功返回 0，否则返回错误码
- **备注**：需要在非运动状态下进入
- **⚠️ 警告**：
  - 该动作存在一定危险性
  - 可能会加速硬件损伤

#### 步态模式接口

##### 26. FreeWalk() - 灵动模式（默认步态）
```cpp
int32_t FreeWalk()
```
- **功能**：进入 AI-灵动模式
- **参数**：无
- **返回值**：成功返回 0，否则返回错误码
- **备注**：
  - 拥有较强的复杂地形适应能力
  - 支持爬楼梯、碎石、草甸、湿滑地面

##### 27. FreeBound() - 并腿跑模式
```cpp
int32_t FreeBound(bool flag)
```
- **功能**：进入/退出并腿跑模式
- **参数**：
  - `flag`：true 进入，false 退出（进入灵动）
- **返回值**：成功返回 0，否则返回错误码

##### 28. FreeJump() - 跳跃模式
```cpp
int32_t FreeJump(bool flag)
```
- **功能**：进入/退出跳跃模式
- **参数**：
  - `flag`：true 进入，false 退出（进入灵动）
- **返回值**：成功返回 0，否则返回错误码
- **备注**：跳跃奔跑步态

##### 29. FreeAvoid() - 闪避模式
```cpp
int32_t FreeAvoid(bool flag)
```
- **功能**：进入/退出闪避模式
- **参数**：
  - `flag`：true 进入，false 退出（进入灵动）
- **返回值**：成功返回 0，否则返回错误码
- **备注**：
  - 移动时可进行避障
  - 静止时可对前方物体进行闪避

##### 30. WalkUpright() - 后腿直立模式
```cpp
int32_t WalkUpright(bool flag)
```
- **功能**：进入/退出后腿直立模式
- **参数**：
  - `flag`：true 进入，false 退出（进入灵动）
- **返回值**：成功返回 0，否则返回错误码
- **备注**：
  - 该步态电机容易过热
  - 请自行把控业务逻辑

##### 31. CrossStep() - 交叉步模式
```cpp
int32_t CrossStep(bool flag)
```
- **功能**：进入/退出交叉步模式
- **参数**：
  - `flag`：true 进入，false 退出（进入灵动）
- **返回值**：成功返回 0，否则返回错误码
- **备注**：
  - 该步态电机容易过热
  - 请自行把控业务逻辑

##### 32. ClassicWalk() - 经典步态
```cpp
int32_t ClassicWalk(bool flag)
```
- **功能**：进入/退出经典步态
- **参数**：
  - `flag`：true 进入，false 退出（进入灵动）
- **返回值**：成功返回 0，否则返回错误码
- **备注**：
  - AI-经典步态，较强的复杂地形适应能力
  - 支持爬楼梯、碎石、草甸、湿滑地面
  - 行走姿态比较稳定优雅

##### 33. TrotRun() - 常规跑步模式
```cpp
int32_t TrotRun()
```
- **功能**：进入常规跑步模式
- **参数**：无
- **返回值**：成功返回 0，否则返回错误码
- **备注**：
  - 跑步步态，最高速度达 3.7m/s
  - 速度较高有一定危险性
  - 不具备复杂地形能力，地面不平容易摔倒

##### 34. StaticWalk() - 常规行走模式
```cpp
int32_t StaticWalk()
```
- **功能**：进入常规行走模式
- **参数**：无
- **返回值**：成功返回 0，否则返回错误码
- **备注**：
  - 原常规模式默认步态
  - 不具备复杂地形能力
  - 行走优雅

##### 35. EconomicGait() - 续航模式
```cpp
int32_t EconomicGait()
```
- **功能**：进入常规续航模式
- **参数**：无
- **返回值**：成功返回 0，否则返回错误码
- **备注**：
  - 机身高度较高，电量消耗速度变慢
  - 单块长续航电池满电行走将延长至 4h 左右

#### 其他功能接口

##### 36. SwitchJoystick() - 遥控器响应开关
```cpp
int32_t SwitchJoystick(bool flag)
```
- **功能**：原生遥控器响应开关
- **参数**：
  - `flag`：true 为响应遥控器，false 为不响应
- **返回值**：成功返回 0，否则返回错误码
- **备注**：关闭后，推动遥控器摇杆不会干涉当前程序运行

##### 37. AutoRecoverSet() - 设置自动翻身
```cpp
int32_t AutoRecoverSet(bool flag)
```
- **功能**：设置自动翻身是否生效
- **参数**：
  - `flag`：true 为生效，false 为失效
- **返回值**：成功返回 0，否则返回错误码
- **备注**：
  - 当设备有背载时建议关闭
  - 摔倒剧烈翻转可能损坏背载设备

##### 38. AutoRecoverGet() - 查询自动翻身状态
```cpp
int32_t AutoRecoverGet(bool& flag)
```
- **功能**：查询自动翻身是否生效
- **参数**：
  - `flag`：输出参数，true 表示已生效，false 表示失效
- **返回值**：成功返回 0，否则返回错误码

##### 39. SwitchAvoidMode() - 闪避模式切换
```cpp
int32_t SwitchAvoidMode()
```
- **功能**：闪避模式下，关闭摇杆未推时前方障碍物的闪避以及后方的障碍物躲避
- **参数**：无
- **返回值**：成功返回 0，否则返回错误码
- **备注**：建议一般不使用

### 1.3 运动状态机（error_code）

通过订阅 `rt/sportmodestate` 话题获取的 `error_code` 字段对应以下运动状态机：

| error_code | 状态机名称 | 说明 |
|-----------|-----------|------|
| 100 | 灵动 | AI-灵动模式 |
| 1001 | 阻尼 | 阻尼状态，急停 |
| 1002 | 站立锁定 | 关节锁定站立 |
| 1004/2006 | 蹲下 | 蹲下状态 |
| 1006 | 特殊动作 | 打招呼/伸懒腰/舞蹈/拜年/比心/开心 |
| 1007 | 坐下 | 坐下状态 |
| 1008 | 前跳 | 前跳动作 |
| 1009 | 扑人 | 向前扑人 |
| 1013 | 平衡站立 | 平衡站立模式 |
| 1015 | 常规行走 | 常规行走模式 |
| 1016 | 常规跑步 | 常规跑步模式 |
| 1017 | 常规续航 | 续航模式 |
| 1091 | 摆姿势 | 摆姿势状态 |
| 2007 | 闪避 | 闪避模式 |
| 2008 | 并腿跑 | 并腿跑模式 |
| 2009 | 跳跃跑 | 跳跃奔跑模式 |
| 2010 | 经典 | 经典步态 |
| 2011 | 倒立 | 倒立模式 |
| 2012 | 前空翻 | 前空翻 |
| 2013 | 后空翻 | 后空翻 |
| 2014 | 左空翻 | 左空翻 |
| 2016 | 交叉步 | 交叉步模式 |
| 2017 | 直立 | 后腿直立模式 |
| 2019 | 牵引 | 牵引模式 |

### 1.4 高层状态接口

#### 状态获取示例

```cpp
#include <unitree/robot/go2/sport/sport_client.hpp>
#include <unitree/common/dds/dds_qos.hpp>

#define TOPIC_HIGHSTATE "rt/sportmodestate"

using namespace unitree::robot;

void HighStateHandler(const void* message)
{
    unitree_go::msg::dds_::SportModeState_ state = 
        *(unitree_go::msg::dds_::SportModeState_*)message;
    
    // 打印位置
    std::cout << "position: " 
              << state.position()[0] << ", "
              << state.position()[1] << ", "
              << state.position()[2] << std::endl;
}

int main(int argc, char **argv)
{
    ChannelFactory::Instance()->Init(0, argv[1]);
    
    // 创建订阅者
    ChannelSubscriber<TOPIC_HIGHSTATE> suber;
    suber.InitChannel(HighStateHandler);
    
    while(1)
    {
        usleep(20000);
    }
    
    return 0;
}
```

#### 可获取的状态信息

```cpp
// 时间戳
TimeSpec stamp();

// 当前模式（error_code）
uint32_t error_code();

// IMU 状态
IMU imu_state();

// 三维位置 [x, y, z] (m)
std::array<float, 3> position();

// 机体高度 (m)
float body_height();

// 三维速度 [vx, vy, vz] (m/s)
std::array<float, 3> velocity();

// 偏航速度 (rad/s)
float yaw_speed();
```

#### IMU 数据获取

```cpp
// 四元数 [w, x, y, z]
std::array<float, 4> quaternion();

// 角速度 [wx, wy, wz] (rad/s)
std::array<float, 3> gyroscope();

// 加速度 [ax, ay, az] (m/s²)
std::array<float, 3> accelerometer();

// 欧拉角 [roll, pitch, yaw] (rad)
std::array<float, 3> rpy();

// 温度 (°C)
int8_t temperature();
```

### 1.5 接口错误码

| 错误号 | 错误描述 |
|-------|---------|
| 4101 | 轨迹点数错误，由客户端返回 |
| 4201 | 动作超时错误，在期望的时间内没有完成指定动作 |
| 4205 | 状态机未初始化结束 |
| 4206 | 执行挥手或拜年类动作前，机器人姿态不佳，不予执行 |
| 3104 | DDS 超时 |

---

## 二、SLAM 导航服务接口

SLAM 和导航服务接口基于 Unitree SDK2，提供建图、定位、导航等功能。

### 2.1 API ID 列表

| API ID | 功能 | 描述 |
|--------|------|------|
| 1901 | 关闭 SLAM | 停止 SLAM 服务，释放计算资源 |
| 1902 | 获取 SLAM 状态 | 获取当前 SLAM 运行状态 |
| 1903 | 导航控制 | 控制机器人导航到目标位姿 |
| 1904 | 暂停导航 | 暂停当前导航任务 |
| 1905 | 继续导航 | 从暂停点继续向目标位姿移动 |

### 2.2 API 详细说明

#### API ID 1901 - 关闭 SLAM

**功能**：停止 SLAM 服务，释放相关计算资源

**输入参数**：
```json
{
  "data": {}
}
```

**反馈数据**：
```json
{
  "status": "success"
}
```

**适用场景**：
- 建图任务完成后
- 导航任务完成后
- 需要切换工作模式时

#### API ID 1903 - 导航控制

**功能**：控制机器人导航到目标位姿

**输入参数**：
```json
{
  "data": {
    "x": 1.0,        // 目标 X 位置 (m)
    "y": 0.0,        // 目标 Y 位置 (m)
    "yaw": 0.0       // 目标偏航角 (rad)
  }
}
```

**反馈数据**：
```json
{
  "status": "success",
  "progress": 0.5    // 导航进度 0-1
}
```

**相关资源**：
- [SLAM 和导航服务接口文档](https://support.unitree.com/home/en/developer/SLAM%20and%20Navigation_service)
- [深度解析 Unitree G1 SLAM 导航服务接口](https://damodev.csdn.net/6979fec7a16c6648a985b395.html)
- [Bilibili 教学视频：Go2 开发教学 10 - SLAM 导航服务接口](https://www.bilibili.com/video/BV1fBYve6Ezr/)

---

## 三、音量灯光服务接口

### 3.1 VuiClient 概述

**VuiClient** 是语音和灯光服务状态服务提供的 Client，通过 RPC 方式实现对 Go2 音量和灯光的控制和信息获取等功能。

**官方文档**：https://support.unitree.com/home/zh/developer/VuiClient

### 3.2 灯光优先级

不同模式下的灯光优先级（从高到低）：
1. 陪伴模式 - 紫色灯光
2. 续航模式 - 黄色灯光
3. 避障 - 对应灯光

---

## 四、其他服务接口

### 4.1 设备状态服务

通过 `RobotStateClient` 可以获取：
- 服务状态
- 设备状态
- 系统资源使用情况

**官方文档**：https://support.unitree.com/home/en/developer/RobotStateClient

### 4.2 DDS 服务接口

Unitree SDK2 是对 DDS 的一层封装，支持 DDS 组件的 QoS 配置，提供简单的封装接口。

**官方文档**：https://support.unitree.com/home/en/developer/DDS_services

### 4.3 避障服务接口

**官方文档**：https://support.unitree.com/home/zh/developer/Obstacle_avoidance_service_interface

### 4.4 运控切换服务接口

**官方文档**：https://support.unitree.com/home/zh/developer/Motion%20Switcher%20Service%20Interface

---

## 五、完整参考资源

### 官方文档中心
- **Go2 SDK 开发指南**：https://support.unitree.com/home/zh/developer
- **运控服务接口 V2.0**：https://support.unitree.com/home/zh/developer/Motion_Services_Interface_V2.0
- **SLAM 导航服务接口**：https://support.unitree.com/home/zh/developer/SLAM_and_Navigation_service
- **音量灯光服务接口**：https://support.unitree.com/home/zh/developer/VuiClient

### GitHub 仓库
- **unitree_sdk2 (C++)**：https://github.com/unitreerobotics/unitree_sdk2
- **unitree_sdk2_python**：https://github.com/unitreerobotics/unitree_sdk2_python
- **unitree_ros2**：https://github.com/unitreerobotics/unitree_ros2

### 教学视频
- **Bilibili：Go2 开发教学系列**：https://www.bilibili.com/video/BV1fBYve6Ezr/

### 深度解析文章
- **Unitree G1 SLAM 导航服务接口深度解析**：https://damodev.csdn.net/6979fec7a16c6648a985b395.html

---

## 六、注意事项

### 版本兼容性
- **适用范围**：Go2 Edu 型号，软件版本 ≥ V1.1.6
- **SDK 更新**：调用接口前，请务必及时更新 unitree_sdk2 到最新版本
- **版本查看**：可通过 Unitree App 查看当前设备软件版本

### 安全警告
- **高难度动作**（空翻、倒立等）：
  - 存在一定危险性，请注意与他人保持安全距离
  - 可能会加速硬件损伤，减少使用寿命
  - 建议谨慎使用

- **电机过热风险**：
  - 倒立模式、交叉步模式、后腿直立模式容易导致电机过热
  - 请自行把控业务逻辑，避免因电机过热导致机身摔倒

- **自动翻身功能**：
  - 当设备有背载时（如云台、相机等传感器），建议关闭自动翻身
  - 摔倒剧烈翻转可能损坏背载设备

### 控制建议
- **Move 接口使用**：
  - 运控部分不会对 Move 指令进行滤波
  - 最新的 Move 指令会维持 1s
  - 建议自行加滤波然后发送
  - 不使用时发送 Move(0,0,0) 或 StopMove()

- **特殊动作执行**：
  - 特殊动作需要在上一个动作执行完毕后再执行
  - 否则会导致动作异常

---

## 七、常见问题 FAQ

### Q1: 如何查看机器人软件版本？
通过 **Unitree App** 查看：App → 设备 → 关于 → 版本信息

### Q2: SDK 版本与机器人版本不匹配怎么办？
请访问 GitHub 仓库 https://github.com/unitreerobotics/unitree_sdk2 更新 SDK 到最新版本。

### Q3: 如何获取机器人状态？
订阅 `rt/sportmodestate` 话题获取高层状态信息。

### Q4: 如何切换步态模式？
使用对应的步态接口函数，如 `FreeWalk()`, `ClassicWalk()`, `TrotRun()` 等。

### Q5: 电机过热如何处理？
1. 立即停止当前动作
2. 调用 `Damp()` 进入阻尼状态
3. 等待电机冷却后继续操作
4. 避免长时间使用容易过热的步态模式

---

*文档版本：1.0*  
*最后更新：2026-07-04*  
*适用 SDK 版本：unitree_sdk2 (master 分支)*

---

**参考资料来源：**
- [Unitree 官方文档中心](https://support.unitree.com/home/zh/developer)
- [运控服务接口 V2.0](https://support.unitree.com/home/zh/developer/Motion_Services_Interface_V2.0)
- [SLAM 和导航服务接口](https://support.unitree.com/home/en/developer/SLAM%20and%20Navigation_service)
- [音量灯光服务接口](https://support.unitree.com/home/zh/developer/VuiClient)
- [unitree_sdk2 GitHub](https://github.com/unitreerobotics/unitree_sdk2)

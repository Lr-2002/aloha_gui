6
⌥
code
code
语雀空间
附件1-cobot_magic详细使用说明文档


附件1-cobot_magic详细使用说明文档
 cobot_magic详细使用说明文档
工控机(4090显卡版,4060显卡版): 支持机械臂遥操作、采集数据、支持模型训练、支持模型推理
ACT模型训练建议使用高算力大显存服务器, 4060显卡训练 50 episode、500 timesteps的数据集,batch-size给4都会出现显存不足。4060可用于推理
遇到问题可参考本手册进行排查（机械臂部分、底盘部分、软件环境部分）。排查结果可联系松灵售后技术支持团队。
出厂时已经配置好了软件环境！！！
拿到设备后，按照第1章第1节接好线，从第3章“采集数据”开始操作
1 上电配置
1.1 电气连接
1.1.1 设备开机操作
先将机械臂水平放置，夹爪，示教器手动重置为闭合状态。每次上电，请先将机械臂恢复到下图正确位置再上电。如果不在正确位置上电，可能导致机械臂零点改变，注意：上电前保证J1刻度对齐。
 
先按下户外电源主开关，再按一下AC开关，此时工控机和机械臂会正常上电。
再按下底盘的电源开关，屏幕、路由器和USB拓展坞由底盘供电。
注：tracer2.0的电源开关在底盘的正前方。
1.1.2 电气连接说明：
户外电源“电小二”：右侧橙色线是它的充电线，从上往下第一个按钮是总电源按钮，ac开关是输出220v交流电开关按钮。
工控机：插在“电小二”上黑色的插头是它的电源适配器插头，通过电小二输出的220v交流电供电。
机械臂：插在“电小二”上白色的插头是它的电源适配器插头，通过电小二输出的220v交流电供电。
（注意：机械臂和工控机的插头可以插在220v插排上取电）
cobot_magic的电气拓扑图如下图所示：
-工控机开机密码为: agx
-路由器WiFi名称：aloha   密码：12345678
下图为出厂接线图，拿到工控机请按照下图所示接线
选配了雷达的设备请勿更改网线网口位置，出厂有做网口绑定。
左臂，右臂和底盘的USB口都有做绑定USB设备口，每条usb线都贴有标签，请勿变动位置，变更会导致can激活异常。
通电后，工控机会自动开机,工控机左侧工作指示灯会亮起。
显示器输出HDMI(DP)线请插入显卡上的HDMI或者DP接口处, 如下图所示。
1.2机械臂接线
出厂时已经接好机械臂的线，开机只需按下户外电源AC接口，参考1.1电气连接。
若发生异常情况，需要给机械臂断电，可以通过按下白色插排的电源按钮。
接通电源后,如下图所示，4条机械臂底座指示灯均亮起绿灯闪烁即表示通电成功,若未亮起绿灯，则检查机械臂供电。
完成机械臂硬件连接并接通电源后，即可实现摇操功能。
2 软件环境配置
此章节的操作出厂前已配置完毕，无需重新配置。
正常使用时请跳过这一章节，直接从3.2节“数据采集”开始！！！
正常使用时请跳过这一章节，直接从3.2节“数据采集”开始！！！
正常使用时请跳过这一章节，直接从3.2节“数据采集”开始！！！
相机部分和机械臂部分检修主体流程可从此章节开始。
cobot_magic的工控机(4060显卡、4090显卡版本),镜像自带ubuntu-20.04、ros1-noetic、cuda-11.3、torch-1.10、conda、python-3.8
数据采集基础配置：ubuntu-20.04、ros1-noetic
模型训练推理配置：1. ubuntu-20.04、ros1-noetic、cuda-11.3、torch-1.10(cuda-11.8、torch-2.1.1), conda,python-3.8, 已测试通过，cuda、torch其他版本请用户自己测试。
2.1 相机配置
大白DC1相机参数
Baseline
40mm
深度距离
0.3-3m
深度图分辨率
640x400x30fps、320x200x30fps
彩色图分辨率
1920x1080x30fps、1280x720x30fps、640x480x30fps
精度
6mm@1m (81%FOV区域参与精度计算)
深度FOV
H 67.9° V 45.3°
彩色FOV
H 71° V 43.7° @ 1920x1080
延迟
30-45ms
数据传输
USB2.0或以上
工作温度
10°C~40°C
尺寸
长59.5x宽17.4x厚11.1 mm
2.1.2 运行
工控机接上相机的usb接口
2.1.3 配置多相机
注意：此章节的操作出厂前已配置完毕，无需重新配置。
这里测试3个相机, 工控机接上3个astra相机的usb
2.2 机械臂配置
ps:出厂时，工控机已经配置好机械臂运行的环境。若非环境损坏，可跳过2.2.1小节。
Cobot_magic机械臂部分检修主体流程可参考此节。
2.2.1 环境安装
1. 安装依赖
2. 机械臂can模块配置(首次配置或更换can设备的USB接口配置)
agx4条机械臂总共2个usb转can模块，需要以下教程来配置
在can_config.sh中，EXPECTED_CAN_COUNT参数一般设置为3( 第95行），因为四条机械臂使用2个can模块（左臂映射名can_left，右臂映射名can_right)，底盘使用1个can模块(底盘映射名can0）。
机械臂按顺序依次进行以下操作：
机械臂上电。
拔掉所有usb转can设备（底盘，左臂，右臂的USB）。
按底盘usb、左臂usb和右臂usb的顺序插入工控机。
终端执行bash find_all_can_port.sh，此时终端会输出can0、can1 和can2的usb地址。
由于刚才按顺序插入，所以映射名和can设备对应关系为（can0->can0，can1->can_left，can2_>can_right)将三个can对应 的usb硬件地址填入臂的can配置脚本中即可（第111行-第113行）。
执行bash can_config.sh,输入密码agx后查看3个can设备是否激活成功。
执行ifconfig | grep can查看是不是有can0，can_left，和can_right，如果有则can模块激活成功。
注意：
每次开机或每次拔插can模块后，都需执行
如果更换了usb端口，请按以上步骤重新配置CAN模块。
通过can_config.sh激活can模块成功后，可通过以下指令检查机械臂的can数据是否能传入工控机。
2.2.2 仅获取主从机械臂关节消息（采集数据，获取机械臂反馈）
然后执行
有如下几个topic：
其中/master/joint_left、/master/joint_right、/puppet/joint_left、/puppet/joint_right可以读取到主臂和从臂的关节数据，例如
2.2.3 通过节点控制从臂（执行重播数据，推理，验证机械臂控制）
先将主臂的数据线断开，再执行以下指令：
然后执行
有如下几个topic：
PS:可参考第3章进行数据采集，数采完成后，按第3.2.3小节 数据重播，若机械臂运动正常，则机械臂部分检修主流程结束（反馈、控制）。
注意事项
执行重播数据，推理，需要先将主臂的数据线断开！！！
在节点参数mode为1的情况向话题/master/joint_left或/master/joint_right发布数据，可控制对侧的从臂运动，因为此时相当于工控机代替主臂。
3 数据采集
默认ubuntu20.04-noetic环境出厂已经配置完成，正常情况下3.1节无需安装。
3.1 环境依赖
3.2 运行
3.2.1 采集数据
1.硬件检查
采集数据前需要保证四条机械臂的航插线插好，且底座亮起绿灯。
2.. 启动机械臂、相机
启动硬件前, 请确保机械臂电源、USB通讯线, 相机USB通讯线成功连接。
如果之前已经启动了机械臂launch文件，采集数据代码就不需要重新启动程序, 只用启动相机launch文件即可。
 rostopic list如下图所示，机械臂4个、相机（大白DC1）3个话题与消息无误，即可采集数据。
2. 话题说明
数采话题说明如下：
话题名
含义
单位
  /master/joint_left	
左侧主臂关节数据
rad
/master/joint_right
右侧主臂关节数据
rad
/puppet/joint_left
左侧从臂关节数据
rad
/puppet/joint_right	
右侧从臂关节数据
rad
/puppet/end_pose_left
左侧从臂末端位姿数据（四元数）
平移分量:m，旋转分量:/
/puppet/end_pose_right
右侧从臂末端位姿数据（四元数）
平移分量:m，旋转分量:/
/puppet/end_pose_euler_left
左侧从臂末端位姿数据（欧拉角）
平移分量:m，旋转分量:rad
/puppet/end_pose_euler_right
右侧从臂末端位姿数据（欧拉角）
平移分量:m，旋转分量:rad
/puppet/arm_status_left
左侧从臂整体状态反馈
/
/puppet/arm_status_right
右侧从臂整体状态反馈
/
/camera_f/color/image_raw
顶部摄像头rgb图像
/
/camera_l/color/image_raw
左臂手腕摄像头rgb图像
/
/camera_r/color/image_raw
右臂手腕摄像头rgb图像
/
/camera_f/aligned_depth_to_color/image_raw
顶部摄像头深度图像
/
/camera_l/aligned_depth_to_color/image_raw	
左臂手腕摄像头深度图像
/
/camera_r/aligned_depth_to_color/image_raw	
右臂手腕摄像头深度图像
/
/camera_f/color/camera_info
顶部摄像头rgb内参
/
/camera_l/color/ camera_info
左臂手腕摄像头rgb内参
/
/camera_r/color/ camera_info
右臂手腕摄像头rgb内参
/
/camera_f/aligned_depth_to_color/camera_info
顶部摄像头深度内参
/
/camera_l/aligned_depth_to_color/camera_info
左臂手腕摄像头深度内参
/
/camera_r/aligned_depth_to_color/camera_info
右臂手腕摄像头深度内参
/
/odom
底盘里程计（仅在开启底盘数采情况出现）
位移平移分量：m,位移旋转分量：/（四元数）；
速度平移分量：m/s，速度旋转分量：rad/s
/tracer_states
底盘状态（以tracer为例，仅在开启底盘数采情况出现）
/
/cmd_vel
底盘控制（仅在开启底盘数采情况出现）
速度平移分量：m/s，速度旋转分量：rad/s。
3. 采集数据
数据采集时终端显示如下图所示：
终端打印sync fail是正常的,仅表示当前时刻没同步传感器数据, 只要终端不是一直sync fail而没有Frame data:  xxx输出, 都是正常现象。
只要终端一直有Frame data:  xxx打印信息,即表示正在记录数据集。
如果打印sync fail,后续没有其他输出, 证明传感器数据没接收到,请按第2章排查相机部分与机械臂部分运行情况。
数据保存路径说明
collect_data.py参数详细介绍
ps:1.深度采集参考：（待更新）
2.一批采集数据集中，每条数据的时间长度(max_timesteps参数）需一致才能用act推理
3.2.2 可视化数据集
 运行
运行上述代码可将3.2.1小节采集数据进行可视化。--dataset_dir、--task_name与--episode_idx参数需要与3.2.1小节采集数据时相同。
可视化结果如下：
终端会打印action,并显示一个彩色图像窗口
运行完成后,会在${dataset_dir}/{task_name}下产生episode_${idx}_qpos.png、episode_${idx}_base_action.png与episode_${idx}_video.mp4文件,目录结构如下：
episode_${idx}_qpos.png
episode_${idx}_base_action.png
 参数说明
--datset_dir 数据集保存路径
--task_name 任务名,作为数据集的文件名
--episode_idx     a动作分块索引号
3.2.3 重播数据集
运行
  执行这一小节请先运行下述指令关闭所有ROS节点。
将采集的数据集包,使用ros发布该数据包的彩色图和机械臂关节姿态。
发布该数据包后,cobot_magic可订阅该消息，示教臂根据数据集中的关节数据开始运动。
 参数说明
--dataset_dir     数据集保存路径
--task_name       任务名,作为数据集的文件名
--episode_idx     动作分块索引号  
--only_pub_puppet 是否只发布主臂的关节姿态消息
4 ACT训练推理
4.1 环境配置
ubuntu-20.04,cuda-11.8,cudnn-8.6.0,torch-2.1.1, python-3.8已测试通过
ubuntu-20.04,cuda-11.3,cudnn-8.6.0,torch-1.10.0,python-3.8已测试通过
出厂已经配置好推理环境，无需重复配置，正常使用请调过该节。
详情请参考mobile-aloha 、act-plus-plus
4.2 数据集采集
参考本文3.2.1(采集数据)小结。
4.3 训练
主要参数参数说明 目前仅支持ACT模型训练
--dataset_dir     数据集目录
--ckpt_dir    训练模型保存目录
--batch_size  训练批量大小
--num_epochs  训练周期
--task_name   任务名称
--pretrain_ckpt 预训练模型路径
--ckpt_name   模型名称
--num_episodes 数据组数
4.4 推理
1
2
3
4
5
6
7
8
9
10
11
12
13
14
15
16
17
18
19
20
21
# 1 新启动一个终端，启动从臂与相机
## 1.1 进入Piper_ros目录
cd cobot_magic/Piper_ros_private-ros-noetic/
source devel/setup.bash

## 1.2 启动2条从臂,启动前需要将机械臂断电重启
**需要拔掉主臂的航空插头**
**需要拔掉主臂的航空插头**
**需要拔掉主臂的航空插头**
roslaunch piper start_ms_piper.launch mode:=1 auto_enable:=true

# 2 推理
## 2.1 激活虚拟环境
conda activate aloha

## 2.2 执行推理
## 2.2.1 进入aloha-devel目录
cd ~/cobot_magic/aloha-devel
## 2.2.2 推理
python act/inference.py --ckpt_dir train
## 推理时注意安全, 如果发现推理表现不正常, 请立即中断代码或断开机械臂电源，以免损伤机械臂
5 Q&A
Q: 遥操作时,由于暴力操作或者误操作导致某条机械臂限位，无法正常工作。
A: 正常的臂归零位状态, 无法正常运作的臂用手托着，然后关闭机械臂所有终端或者断电，重新启动即可
Q: 启动底盘后, 有里程计/odom消息, 但是移动车,/odom数据始终处于0数据。
A: 底盘can使能, 然后重新启动底盘程序
Q：如何查看ros话题频率
A: 终端输入rostopic hz 话题名称即可打印该话题频率
Q: 运行collect_data.py脚本，如果代码报错
A: 请使用cobot_magic自带的镜像环境
Q: 运行collect_data.py脚本，如果终端一直打印sync fail
A: 请检查collect_data.py收集的ros话题是否有正常输出, 没有正常输出请检查各话题名是否对应
Q：终端报错信息如下：
1
2
3
4
RLException: roscore cannot run as another roscore/master is already running. 
Please kill other roscore/master processes before relaunching.
The ROS_MASTER_URI is http://PC:11311/
The traceback for the exception was written to the log file
A: 由于重复启动roscore导致, 可以重启或者注销电脑
Q: 底盘ros里程计消息/odom打印,数字没有变化
A: 确定底盘can2usb线是否成功连接和底盘can是否使能

覃智辉、何士玉、谢瑞亲等01-09 19:156541
0
IP 属地广东
举报
Lr_2002

关于语雀数据安全English
大纲
cobot_magic详细使用说明文档
拿到设备后，按照第1章第1节接好线，从第3章“采集数据”开始操作
1 上电配置
1.1 电气连接
1.1.1 设备开机操作
1.1.2 电气连接说明：
1.2机械臂接线
2 软件环境配置
此章节的操作出厂前已配置完毕，无需重新配置。
正常使用时请跳过这一章节，直接从3.2节“数据采集”开始！！！
正常使用时请跳过这一章节，直接从3.2节“数据采集”开始！！！
正常使用时请跳过这一章节，直接从3.2节“数据采集”开始！！！
2.1 相机配置
2.1.2 运行
2.1.3 配置多相机
注意：此章节的操作出厂前已配置完毕，无需重新配置。
2.2 机械臂配置
2.2.1 环境安装
1. 安装依赖
2. 机械臂can模块配置(首次配置或更换can设备的USB接口配置)
2.2.2 仅获取主从机械臂关节消息（采集数据，获取机械臂反馈）
2.2.3 通过节点控制从臂（执行重播数据，推理，验证机械臂控制）
注意事项
3 数据采集
3.1 环境依赖
3.2 运行
3.2.1 采集数据
1.硬件检查
2.. 启动机械臂、相机
2. 话题说明
3. 采集数据
3.2.2 可视化数据集
1. 运行
2. 参数说明
3.2.3 重播数据集
1. 运行
2. 参数说明
4 ACT训练推理
4.1 环境配置
4.2 数据集采集
4.3 训练
4.4 推理
5 Q&A
Adblocker


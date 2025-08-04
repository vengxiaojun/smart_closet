# smart_closet
# 智尚衣镜 · AI 穿搭系统

云-边-端全链路虚拟试衣与智能搭配解决方案。

## ✨ 功能速览

- **电子衣柜**：手机拍照自动分类录入。
- **智能搭配**：单件衣物与实时场景智能搭配
- **虚拟试衣**：优化leffa模型，快速高效沉浸试衣
- **语音控制**：搭配乐鑫Atoms3r开发板实现实时语音对话控制，解放双手
- **个性反馈**：搭配反馈记录，记住你的搭配喜好。

## 🏗️ 整体架构

![系统架构.drawio](D:\大三下\物联网\系统架构.drawio.png)

## 🚀 快速开始

1. 克隆仓库  

   ```bash
   git clone https://github.com/<your-org>/smart-mirror.git && cd smart-mirror
   ```

2. 部署leffa server

   leffa 目录下包含优化后的leffa代码，建议使用算力强悍的GPU部署

   ```bash
   cd leffa
   ```

   ```bash
   #此处建议创建虚拟环境后进行下一步
   pip install -r requiremens.txt
   ```

   ```bash
   python server.py 
   ```

   

2. 运行Django项目

   ```bash
   cd Django_webapp
   ```

   ```bash
   #此处建议创建虚拟环境后进入下一步
   pip install -r requirements.txt
   ```
   
   ```bash
   python manage.py runserver 0.0.0.0:8000
   ```

   

## 🛠️ 技术栈

表格

复制

| 层级 | 技术                           |
| :--- | :----------------------------- |
| 感知 | AtomS3R-M12 + 8 MP 摄像头      |
| 边缘 | ESP-IDF 5.1, YOLOv8-nano       |
| App  | Flutter 3.16                   |
| 云端 | FastAPI, 火山引擎 IoT & 大模型 |

## 📄 License

MIT © 2024 Smart Mirror Team

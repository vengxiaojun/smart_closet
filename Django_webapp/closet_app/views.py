from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import json, base64, io, os
from PIL import Image
import asyncio
import websockets, socket
import logging, struct
from django.conf import settings
import requests
import time, uuid
import shutil
from cozepy import Coze, TokenAuth, WorkflowEventType
from django.conf import settings
from .seafile_utils import (
    safe_seafile_list, 
    safe_seafile_upload_file, 
    safe_seafile_delete, 
    safe_seafile_download_url,
    filter_files_by_type,
    get_file_count_by_type
)
from rembg import remove
from io import BytesIO
import numpy as np
import re
from datetime import datetime

# 配置日志
logger = logging.getLogger(__name__)

# WebSocket连接配置
LEFFA_WEBSOCKET_URL = "ws://your-leffa-server.com:8000/ws/try-on/"  # 替换为实际的Leffa服务器地址

# 统一本地备注文件存储路径
BASE_DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
if not os.path.exists(BASE_DATA_DIR):
    os.makedirs(BASE_DATA_DIR)
REMARKS_PATH = os.path.join(BASE_DATA_DIR, 'closet_remarks.json')
BODY_REMARKS_PATH = os.path.join(BASE_DATA_DIR, 'body_remarks.json')
USERINF_DIR = os.path.join(settings.BASE_DIR, 'static', 'userinf')

# 初始化Coze客户端
coze = Coze(auth=TokenAuth(token=settings.COZE_TOKEN), base_url=settings.COZE_API_BASE)

# JSON文件版本计数器
json_version_counter = {}

@csrf_exempt
def leffa_process(request):
    if request.method == 'POST':
        try:
            logger.info("=== 开始处理试穿请求 ===")
            
            human_image_file = request.FILES.get('human_image')
            clothing_image_file = request.FILES.get('clothing_image')
            
            logger.info(f"接收到人体图像: {human_image_file.name if human_image_file else 'None'}")
            logger.info(f"接收到衣物图像: {clothing_image_file.name if clothing_image_file else 'None'}")
            
            if not human_image_file or not clothing_image_file:
                logger.error("缺少人体图像或衣物图像")
                return JsonResponse({'error': '缺少人体图像或衣物图像'}, status=400)
            
            # 转 base64
            logger.info("开始转换图像为base64...")
            human_b64 = imagefile_to_base64(human_image_file)
            clothing_b64 = imagefile_to_base64(clothing_image_file)
            logger.info(f"人体图像base64长度: {len(human_b64)}")
            logger.info(f"衣物图像base64长度: {len(clothing_b64)}")
            
            # 调用 socket 通信
            logger.info("开始调用socket通信到8899端口...")
            result = send_socket_request(human_b64, clothing_b64, server_ip='127.0.0.1', server_port=8899)
            logger.info(f"Socket通信结果: {result}")
            
            if "error" in result:
                logger.error(f"Socket通信失败: {result['error']}")
                return JsonResponse({'success': False, 'error': result['error']}, status=500)
            else:
                # 返回生成的试穿图像（base64）
                logger.info("试穿图像生成成功")
                return JsonResponse({
                    'success': True,
                    'image_data': result.get("gen_image"),
                    'mask': result.get("mask"),
                    'densepose': result.get("densepose"),
                    'message': '试穿图像生成成功'
                })
        except Exception as e:
            logger.error(f"试穿处理异常: {str(e)}")
            return JsonResponse({'success': False, 'error': str(e)}, status=500)
    else:
        return JsonResponse({'error': '只支持 POST 请求'}, status=405)

async def send_websocket_request(data):
    """通过WebSocket发送请求到Leffa服务器"""
    try:
        # 连接到Leffa WebSocket服务器
        async with websockets.connect(LEFFA_WEBSOCKET_URL) as websocket:
            # 发送试穿请求
            await websocket.send(json.dumps(data))
            
            # 接收响应
            response = await websocket.recv()
            result = json.loads(response)
            
            return result
            
    except websockets.exceptions.ConnectionClosed:
        logger.error("WebSocket连接已关闭")
        return {'success': False, 'error': 'WebSocket连接已关闭'}
    except websockets.exceptions.InvalidURI:
        logger.error("无效的WebSocket URI")
        return {'success': False, 'error': '无效的WebSocket URI'}
    except Exception as e:
        logger.error(f"WebSocket通信失败: {str(e)}")
        return {'success': False, 'error': f'WebSocket通信失败: {str(e)}'}

#新增的后端功能起始
def index(request):
    return render(request, 'closet_app/home.html')

def closet_function(request):
    """从云端获取衣柜数据并显示"""
    # 定义分类名称映射（左侧显示名称与图片前缀的对应关系）
    # 键：模板中显示的分类名称（如"T恤"），值：图片文件名前缀（如"T-shirt"）
    category_mapping = {
        "T恤": "T-SHIRT",
        "外套": "COAT",
        "连衣裙": "DRESS",
        "开衫": "CARDIGAN",
        "长裤": "TROUSERS",
        "衬衫": "SHIRT",
        "短裙": "SHORT-SKIRT",
        "正装": "SUIT",
        "短裤": "SHORTS",
        "卫衣": "SWEATSHIRT"
    }
    
    try:
        # 从云端获取衣柜数据
        closet_data = load_closet_json()
        logger.info(f"从云端获取到衣柜数据: {len(closet_data)} 件衣物")
        
        # 初始化分类图片字典（按左侧显示名称分组）
        closet_images = {category: [] for category in category_mapping.keys()}
        
        # 遍历云端衣柜数据
        for filename, file_info in closet_data.items():
            # 过滤非图片文件（只保留常见图片格式）
            if filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
                # 获取衣物类型
                clothing_type = file_info.get('type', '').upper()
                logger.info(f"处理衣物: {filename}, 类型: {clothing_type}")
                
                # 匹配图片对应的分类（根据衣物类型）
                matched = False
                for display_name, type_prefix in category_mapping.items():
                    # 精确匹配逻辑：完全匹配或前缀匹配，但避免子字符串误匹配
                    if (clothing_type == type_prefix or 
                        clothing_type.startswith(type_prefix + '-') or
                        (type_prefix == 'SHIRT' and clothing_type == 'SHIRT') or
                        (type_prefix == 'SWEATSHIRT' and clothing_type == 'SWEATSHIRT')):
                        
                        # 获取云端图片URL
                        file_path = settings.SEAFILE_CLOSET_DIR + filename
                        image_url = safe_seafile_download_url(file_path)
                        if image_url:
                            # 构造图片信息（包含URL和备注）
                            image_info = {
                                'url': image_url,
                                'filename': filename,
                                'remark': file_info.get('features', ''),
                                'type': clothing_type
                            }
                            # 添加到对应分类的列表中
                            closet_images[display_name].append(image_info)
                            logger.info(f"成功添加衣物到分类 {display_name}: {filename}")
                        else:
                            logger.warning(f"无法获取图片URL: {file_path}")
                        matched = True
                        break  # 匹配到分类后跳出循环，避免重复添加
                
                # 如果没有匹配到任何分类，记录日志
                if not matched:
                    logger.warning(f"衣物 {filename} (类型: {clothing_type}) 未匹配到任何分类")
        
        # 将分类图片数据传递到模板
        return render(request, 'closet_app/closet.html', {
            'closet_images': closet_images  # 模板中用此变量循环展示图片
        })
        
    except Exception as e:
        logger.error(f"获取衣柜数据失败: {e}")
        # 如果获取失败，返回空的衣柜数据
        closet_images = {category: [] for category in category_mapping.keys()}
        return render(request, 'closet_app/closet.html', {
            'closet_images': closet_images
        })

def match_function(request):
    base_static_path = os.path.join(settings.BASE_DIR, 'static', 'Mycoord')  # 假设图片都放在 static/mycoord 里
    
    categories = ['working', 'leisure', 'party', 'sports']
    images_dict = {}

    for cat in categories:
        prefix = f"{cat}_"  # 如 working_
        images = []
        if os.path.exists(base_static_path):
            for filename in os.listdir(base_static_path):
                # 支持多种图片格式：jpg, jpeg, png, webp
                if (filename.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')) and 
                    filename.startswith(prefix)):
                    images.append(f"Mycoord/{filename}")  # 传给模板的路径，相对于 static
        images_dict[cat] = images

    context = {
        'images_dict': images_dict,
    }
    return render(request, 'closet_app/matching.html',context)

def profile_function(request):
    return render(request, 'closet_app/profile.html')

def mirror_function(request):
    return render(request, 'closet_app/mirror.html')

def test_cloud(request):
    return render(request, 'closet_app/test_cloud.html')

def test_users(request):
    return render(request, 'closet_app/test_users.html')

@csrf_exempt
def speech_function(request):
    if request.method == 'POST':
        # 此处需要填写语音接收、处理逻辑
        # 接收语音内容，调用语音智能体进行处理
        data = json.loads(request.body)
        speech_content = data.get('speech_content')
        # 调用语音智能体处理语音内容
        # 示例返回，实际需要替换
        result = {'需求': '示例需求'}
        return JsonResponse(result)
    return JsonResponse({'error': '只支持 POST 请求'}, status=405)

@csrf_exempt
def image_function(request):
    if request.method == 'POST':
        # 此处需要填写图像接收、处理逻辑
        # 根据请求参数（人体信息还是衣物信息）处理图片
        data = json.loads(request.body)
        request_type = data.get('request_type')  # '人体录入' 或 '衣物录入'
        # 调用摄像头拍照，处理图片并保存
        # 示例返回，实际需要替换
        save_path = '示例数据保存路径'
        return JsonResponse({'数据保存路径': save_path})
    return JsonResponse({'error': '只支持 POST 请求'}, status=405)

# ========== 云端存储相关函数 ==========

def generate_json_filename(base_name):
    """
    生成带时间戳和版本号的JSON文件名
    格式: base_name_YYMMDDHHMMSS_XX.json
    例如: closet_250712112001_01.json
    """
    now = datetime.now()
    date_str = now.strftime("%y%m%d")  # 25年07月12日
    time_str = now.strftime("%H%M%S")  # 11时20分01秒
    
    # 获取当前分钟内的版本号
    minute_key = f"{date_str}_{time_str[:-2]}"  # 精确到分钟
    if minute_key not in json_version_counter:
        json_version_counter[minute_key] = 1
    else:
        json_version_counter[minute_key] += 1
    
    version = f"{json_version_counter[minute_key]:02d}"
    
    return f"{base_name}_{date_str}{time_str}_{version}.json"

def get_simple_filename(clothing_type, file_count=None):
    """
    生成简化的文件名，格式：T-SHIRT-001.jpg
    使用智能编号算法，避免删除后的撞编号问题
    """
    if not clothing_type:
        clothing_type = 'UNKNOWN'
    
    # 清理和标准化衣物类型
    type_clean = str(clothing_type).strip().upper()
    # 移除常见的无关词汇
    type_clean = re.sub(r'\b(CONTENT|CATEGORY|TYPE|CLASS)\b', '', type_clean, flags=re.IGNORECASE)
    type_clean = re.sub(r'[^\w\-]', '-', type_clean)
    type_clean = re.sub(r'-+', '-', type_clean)
    type_clean = type_clean.strip('-')
    
    # 如果类型为空或只包含无关词汇，使用默认值
    if not type_clean or type_clean == '':
        type_clean = 'UNKNOWN'
    
    # 获取当前类型的所有已使用编号
    used_numbers = get_used_numbers_for_type(type_clean)
    
    # 找到最小的未使用编号
    next_number = 1
    while next_number in used_numbers:
        next_number += 1
    
    # 生成文件名
    filename = f"{type_clean}-{next_number:03d}.jpg"
    logger.info(f"生成文件名: {clothing_type} -> {filename}")
    return filename

def parse_classify_result(classify_result):
    """
    解析分类结果，正确提取type和features
    支持Coze返回的特殊格式
    """
    try:
        print(f"=== 开始解析分类结果 ===")
        print(f"输入类型: {type(classify_result)}")
        print(f"输入内容: {classify_result}")
        print(f"输入内容repr: {repr(classify_result)}")
        
        # 空值处理
        if not classify_result or str(classify_result).strip() in ('', 'null', '{}', 'None', "='{\"\"", "='{\"\"}"):
            print(f"=== 检测到空值，返回unknown ===")
            return 'unknown', ''
        
        # 检查是否是Coze返回的对象格式（包含content字段）
        if hasattr(classify_result, 'content') and classify_result.content:
            print(f"=== 检测到Coze对象格式，提取content字段 ===")
            print(f"content字段内容: {classify_result.content}")
            # 使用content字段的内容进行解析
            result_str = str(classify_result.content)
        else:
            # 将结果转换为字符串
            result_str = str(classify_result)
        
        print(f"=== 转换为字符串 ===")
        print(f"字符串内容: {result_str}")
        print(f"字符串长度: {len(result_str)}")
        logger.info(f"原始分类结果: {result_str}")
        
        # 尝试解析为JSON（这是Coze返回的标准格式）
        try:
            print(f"=== 尝试JSON解析 ===")
            classify_data = json.loads(result_str)
            print(f"JSON解析成功: {classify_data}")
            logger.info(f"JSON解析成功: {classify_data}")
            
            # 提取分类信息 - 优先使用category字段
            clothing_type = classify_data.get('category', classify_data.get('种类', classify_data.get('type', 'unknown')))
            features = classify_data.get('features', classify_data.get('特征', classify_data.get('description', '')))
            
            print(f"从JSON提取 - 类型: {clothing_type}, 特征: {features}")
            
            # 如果features是列表，转换为字符串
            if isinstance(features, list):
                features = ', '.join(features)
                print(f"features转换为字符串: {features}")
            
        except json.JSONDecodeError as e:
            print(f"=== JSON解析失败: {e} ===")
            logger.info("JSON解析失败，尝试其他解析方式")
            
            # 使用正则表达式直接提取category和features
            print(f"=== 使用正则表达式解析 ===")
            category_match = re.search(r'"category":"([^"]+)"', result_str)
            features_match = re.search(r'"features":"([^"]*)"', result_str)
            
            if category_match:
                clothing_type = category_match.group(1)
                print(f"正则提取的category: {clothing_type}")
            else:
                clothing_type = 'unknown'
                print(f"未找到category字段")
            
            if features_match:
                features = features_match.group(1)
                print(f"正则提取的features: {features}")
            else:
                features = ''
                print(f"未找到features字段")
            
            print(f"正则解析成功: 类型={clothing_type}, 特征={features}")
            logger.info(f"正则解析成功: 类型={clothing_type}, 特征={features}")
            return clothing_type, features
            
            # 如果不是JSON格式，尝试从字符串中提取信息
            result_str = result_str.strip()
            print(f"清理后的字符串: {result_str}")
            
            # 尝试提取类型和特征
            if ':' in result_str:
                # 格式可能是 "类型: 特征" 或 "种类: 特征"
                parts = result_str.split(':', 1)
                clothing_type = parts[0].strip()
                features = parts[1].strip() if len(parts) > 1 else ''
                print(f"按冒号分割 - 类型: {clothing_type}, 特征: {features}")
            else:
                # 直接使用整个字符串作为类型
                clothing_type = result_str
                features = ''
                print(f"直接使用字符串作为类型: {clothing_type}")
        
        # 确保类型是字符串并清理
        clothing_type = str(clothing_type).strip()
        features = str(features).strip()
        print(f"=== 清理前的类型: {clothing_type} ===")
        
        # 清理无关词汇 - 但保留category作为有效词汇
        clothing_type = re.sub(r'\b(CONTENT|TYPE|CLASS)\b', '', clothing_type, flags=re.IGNORECASE)
        clothing_type = re.sub(r'-+', '-', clothing_type)
        clothing_type = clothing_type.strip('-')
        print(f"=== 清理后的类型: {clothing_type} ===")
        
        # 如果clothing_type为空
        if not clothing_type:
            clothing_type = 'unknown'
            print(f"=== 类型为空，设为unknown ===")
        # 如果clothing_type包含特殊字符或太长，进行清理
        if len(clothing_type) > 50:
            clothing_type = clothing_type[:50]
            print(f"=== 类型过长，截取为: {clothing_type} ===")
        
        print(f"=== 最终解析结果 ===")
        print(f"类型: {clothing_type}")
        print(f"特征: {features}")
        logger.info(f"解析结果 - 类型: {clothing_type}, 特征: {features}")
        return clothing_type, features
        
    except Exception as e:
        print(f"=== 解析过程出现异常 ===")
        print(f"异常类型: {type(e)}")
        print(f"异常内容: {e}")
        logger.error(f"解析分类结果失败: {e}")
        return 'unknown', ''

@csrf_exempt
def save_user(request):
    if request.method == 'POST':
        user_id = request.POST.get('id')
        name = request.POST.get('name')
        gender = request.POST.get('gender')
        age = request.POST.get('age')
        height = request.POST.get('height')
        weight = request.POST.get('weight')
        style = request.POST.get('style')
        photo = request.FILES.get('photo')

        # 验证必填字段
        if not name or not gender or not age or not height or not weight:
            return JsonResponse({'success': False, 'error': '请填写所有必填信息'})

        # 生成安全用户名
        safe_name = "".join(c for c in name if c.isalnum() or c in (' ', '-', '_')).rstrip()
        safe_name = safe_name.replace(' ', '_')
        json_filename = f'{safe_name}.json'
        photo_filename = f'{safe_name}.jpg'
        json_path = os.path.join(USERINF_DIR, json_filename)
        photo_path = os.path.join(USERINF_DIR, photo_filename)
        photo_url = f'/static/userinf/{photo_filename}'

        # 检查是否为编辑（有id）
        old_json_path = None
        old_photo_path = None
        old_user_data = None
        if user_id:
            # 查找旧的json和jpg文件（id可能是旧用户名或数字）
            for file in os.listdir(USERINF_DIR):
                if file.endswith('.json'):
                    with open(os.path.join(USERINF_DIR, file), 'r', encoding='utf-8') as f:
                        try:
                            data = json.load(f)
                            if str(data.get('id')) == str(user_id):
                                old_json_path = os.path.join(USERINF_DIR, file)
                                old_photo_path = os.path.join(USERINF_DIR, os.path.splitext(file)[0] + '.jpg')
                                old_user_data = data  # 保存原有用户数据
                                break
                        except Exception:
                            continue
            
            # 编辑用户时，保持原有的文件名，不重命名
            if old_json_path:
                json_path = old_json_path
                photo_path = old_photo_path
                if old_photo_path:
                    photo_filename = os.path.basename(old_photo_path)
                    photo_url = f'/static/userinf/{photo_filename}'
                else:
                    photo_filename = f'{safe_name}.jpg'
                    photo_url = f'/static/userinf/{photo_filename}'
        else:
            # 新用户，id用用户名
            user_id = safe_name

        # 保存图片（如有新上传）
        if photo and photo_path:
            with open(photo_path, 'wb+') as destination:
                for chunk in photo.chunks():
                    destination.write(chunk)
            photo_url = f'/static/userinf/{photo_filename}'
        elif old_photo_path and os.path.exists(old_photo_path):
            # 没有新上传但有旧照片，保持原url
            photo_url = f'/static/userinf/{photo_filename}'
        else:
            photo_url = ''

        # 构建用户数据，保留原有的is_default字段
        user_data = {
            'id': user_id,
            'name': name,
            'gender': gender,
            'age': age,
            'height': height,
            'weight': weight,
            'style': style,
            'photo_url': photo_url,
        }
        
        # 如果是编辑用户，保留原有的is_default字段
        if old_user_data:
            user_data['is_default'] = old_user_data.get('is_default', False)
        else:
            user_data['is_default'] = False  # 新用户默认为非默认用户

        # 保存用户信息到JSON文件
        try:
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(user_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存用户信息失败: {e}")
            return JsonResponse({'success': False, 'error': f'保存失败: {str(e)}'})

        logger.info(f"用户信息保存成功: {name}, ID: {user_id}")
        return JsonResponse({'success': True, 'user_id': user_id})
    
    return JsonResponse({'success': False, 'error': '只支持POST请求'})

def load_users(request):
    users = []
    for file in os.listdir(USERINF_DIR):
        if file.endswith('.json'):
            try:
                with open(os.path.join(USERINF_DIR, file), 'r', encoding='utf-8') as f:
                    user_data = json.load(f)
                    # 确保is_default字段存在，默认为False
                    if 'is_default' not in user_data:
                        user_data['is_default'] = False
                    users.append(user_data)
            except Exception as e:
                logger.error(f"读取用户文件失败 {file}: {e}")
                continue
    return JsonResponse({'users': users})

def get_user(request):
    user_id = request.GET.get('id')
    if not user_id:
        return JsonResponse({'success': False, 'error': '缺少用户ID'})
    
    # 查找用户文件（可能文件名与user_id不同）
    for file in os.listdir(USERINF_DIR):
        if file.endswith('.json'):
            try:
                file_path = os.path.join(USERINF_DIR, file)
                with open(file_path, 'r', encoding='utf-8') as f:
                    user_data = json.load(f)
                    if str(user_data.get('id')) == str(user_id):
                        return JsonResponse(user_data)
            except Exception as e:
                logger.error(f"读取用户文件失败 {file}: {e}")
                continue
    
    return JsonResponse({'success': False, 'error': '用户不存在'})

@csrf_exempt
def delete_user(request):
    if request.method == 'POST':
        user_id = request.GET.get('id')
        if not user_id:
            return JsonResponse({'success': False, 'error': '缺少用户ID'})
        
        # 查找用户文件（可能文件名与user_id不同）
        user_file = None
        photo_file = None
        for file in os.listdir(USERINF_DIR):
            if file.endswith('.json'):
                try:
                    file_path = os.path.join(USERINF_DIR, file)
                    with open(file_path, 'r', encoding='utf-8') as f:
                        user_data = json.load(f)
                        if str(user_data.get('id')) == str(user_id):
                            user_file = file_path
                            photo_file = os.path.join(USERINF_DIR, os.path.splitext(file)[0] + '.jpg')
                            break
                except Exception:
                    continue
        
        if user_file and os.path.exists(user_file):
            os.remove(user_file)
        if photo_file and os.path.exists(photo_file):
            os.remove(photo_file)
        return JsonResponse({'success': True})
    return JsonResponse({'success': False, 'error': '只支持POST请求'})

@csrf_exempt
def set_default_user(request):
    """设置默认用户"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            user_id = data.get('user_id')
            
            if not user_id:
                return JsonResponse({'success': False, 'error': '缺少用户ID'})
            
            # 查找用户文件（可能文件名与user_id不同）
            user_file = None
            for file in os.listdir(USERINF_DIR):
                if file.endswith('.json'):
                    try:
                        file_path = os.path.join(USERINF_DIR, file)
                        with open(file_path, 'r', encoding='utf-8') as f:
                            user_data = json.load(f)
                            if str(user_data.get('id')) == str(user_id):
                                user_file = file_path
                                break
                    except Exception:
                        continue
            
            if not user_file:
                return JsonResponse({'success': False, 'error': '用户不存在'})
            
            # 先清除所有用户的默认状态
            for file in os.listdir(USERINF_DIR):
                if file.endswith('.json') and file != 'default_user.json':
                    try:
                        file_path = os.path.join(USERINF_DIR, file)
                        with open(file_path, 'r', encoding='utf-8') as f:
                            user_data = json.load(f)
                        
                        # 清除默认状态
                        if 'is_default' in user_data:
                            user_data['is_default'] = False
                            with open(file_path, 'w', encoding='utf-8') as f:
                                json.dump(user_data, f, ensure_ascii=False, indent=2)
                    except Exception as e:
                        logger.warning(f"清除用户默认状态失败 {file}: {e}")
                        continue
            
            # 设置指定用户为默认用户
            with open(user_file, 'r', encoding='utf-8') as f:
                user_data = json.load(f)
            
            user_data['is_default'] = True
            user_data['default_set_time'] = time.time()
            
            with open(user_file, 'w', encoding='utf-8') as f:
                json.dump(user_data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"设置默认用户成功: {user_id}")
            return JsonResponse({'success': True, 'message': '默认用户设置成功'})
            
        except Exception as e:
            logger.error(f"设置默认用户失败: {e}")
            return JsonResponse({'success': False, 'error': f'设置失败: {str(e)}'})
    
    return JsonResponse({'success': False, 'error': '只支持POST请求'})

def get_default_user(request):
    """获取默认用户信息（向后兼容）"""
    try:
        # 使用load_users的逻辑查找默认用户
        for file in os.listdir(USERINF_DIR):
            if file.endswith('.json'):
                try:
                    file_path = os.path.join(USERINF_DIR, file)
                    with open(file_path, 'r', encoding='utf-8') as f:
                        user_data = json.load(f)
                    
                    # 检查是否为默认用户
                    if user_data.get('is_default', False):
                        return JsonResponse({
                            'success': True,
                            'default_user': user_data,
                            'set_time': user_data.get('default_set_time')
                        })
                except Exception as e:
                    logger.warning(f"读取用户文件失败 {file}: {e}")
                    continue
        
        return JsonResponse({'success': False, 'error': '未设置默认用户'})
        
    except Exception as e:
        logger.error(f"获取默认用户失败: {e}")
        return JsonResponse({'success': False, 'error': f'获取失败: {str(e)}'})

@csrf_exempt
def outfit_display_function(request):
    if request.method == 'POST':
        # 此处需要填写衣物搭配展示逻辑
        # 调用试穿模型获取试穿图和特定姿态
        # 示例返回，实际需要替换
        trial_images = ['示例试穿图 1', '示例试穿图 2']
        poses = ['姿态 1', '姿态 2']
        return JsonResponse({'试穿图': trial_images, '特定姿态': poses})
    return JsonResponse({'error': '只支持 POST 请求'}, status=405)

@csrf_exempt
def clothing_try_on_function(request):
    if request.method == 'POST':
        # 此处需要填写衣物试穿逻辑
        # 调用摄像头进行人体录入和衣物录入，送给 leffa 获取试穿图像
        # 示例返回，实际需要替换
        try_on_image = '示例试穿图像'
        return JsonResponse({'试穿图像': try_on_image})
    return JsonResponse({'error': '只支持 POST 请求'}, status=405)

def imagefile_to_base64(image_file):
    return base64.b64encode(image_file.read()).decode()

def send_socket_request(human_b64, clothing_b64, server_ip='127.0.0.1', server_port=8899):
    # 通过ssh隧道映射到服务器8899端口，进行衣物试穿图像生成
    logger.info(f"=== 开始Socket通信 ===")
    logger.info(f"目标服务器: {server_ip}:{server_port}")
    
    data = {
        "control_type": "virtual_tryon",
        "vt_src_image": human_b64,
        "vt_ref_image": clothing_b64,
        "params": {
            "ref_acceleration": False,
            "step": 30,
            "scale": 2.5,
            "seed": 42,
            "vt_model_type": "viton_hd",
            "vt_garment_type": "dresses",
            "vt_repaint": False,
            "preprocess_garment": False
        }
    }
    
    try:
        json_bytes = json.dumps(data).encode()
        json_length = struct.pack('!I', len(json_bytes))
        logger.info(f"准备发送数据，JSON长度: {len(json_bytes)} bytes")
        
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client_socket:
            logger.info("尝试连接到服务器...")
            client_socket.connect((server_ip, server_port))
            logger.info("连接成功，开始发送数据...")
            
            client_socket.sendall(json_length)
            client_socket.sendall(json_bytes)
            logger.info("数据发送完成，等待响应...")
            
            result_length_bytes = client_socket.recv(4)
            result_length = struct.unpack('!I', result_length_bytes)[0]
            logger.info(f"接收到响应长度: {result_length} bytes")
            
            result_data = b""
            while len(result_data) < result_length:
                packet = client_socket.recv(result_length - len(result_data))
                if not packet:
                    break
                result_data += packet
            
            logger.info(f"接收完整响应，长度: {len(result_data)} bytes")
            result = json.loads(result_data)
            logger.info(f"解析响应成功: {result}")
            return result
            
    except ConnectionRefusedError:
        error_msg = f"连接被拒绝，请检查服务器 {server_ip}:{server_port} 是否运行"
        logger.error(error_msg)
        return {"error": error_msg}
    except socket.timeout:
        error_msg = "连接超时"
        logger.error(error_msg)
        return {"error": error_msg}
    except Exception as e:
        error_msg = f"Socket通信失败: {str(e)}"
        logger.error(error_msg)
        return {"error": error_msg}

@csrf_exempt
def classify_clothing(request):
    if request.method == 'POST':
        image_file = request.FILES.get('image')
        if not image_file:
            logger.error("未接收到图片文件")
            return JsonResponse({'success': False, 'error': '未上传图片'})
        
        logger.info(f"接收到图片文件: {image_file.name}, 大小: {image_file.size} bytes")
        
        try:
            # 1. 保存图片到本地临时目录
            temp_filename = f"temp_{int(time.time())}.jpg"
            temp_path = os.path.join(settings.TEMP_DIR, temp_filename)
            
            with open(temp_path, 'wb') as f:
                for chunk in image_file.chunks():
                    f.write(chunk)
            
            # 2. 上传到Seafile的TEMP目录
            if not safe_seafile_upload_file(temp_path, settings.SEAFILE_TEMP_DIR):
                return JsonResponse({'success': False, 'error': '上传到临时目录失败'})
            
            # 3. 获取图片的下载链接
            temp_file_path = settings.SEAFILE_TEMP_DIR + temp_filename
            image_url = safe_seafile_download_url(temp_file_path)
            if not image_url:
                return JsonResponse({'success': False, 'error': '获取图片链接失败'})
            
            # 4. 调用Coze平台进行分类
            classify_result = call_coze_classify(image_url)
            if not classify_result:
                logger.error("Coze分类返回空结果")
                return JsonResponse({
                    'success': False, 
                    'error': '分类失败：服务器暂时繁忙，请稍后重试。如果问题持续存在，请联系管理员。'
                })
            
            # 5. 解析分类结果
            clothing_type, features = parse_classify_result(classify_result)
            logger.info(f"分类结果解析完成: 类型={clothing_type}, 特征={features}")
            
            # 验证分类结果
            if not clothing_type or clothing_type == 'unknown':
                logger.error("分类结果无效")
                return JsonResponse({'success': False, 'error': '分类失败：无法识别衣物类型'})
            
            # 6. 处理图片（抠图、加白底、裁剪）
            original_image = seafile_access_image(temp_file_path)
            if original_image:
                # 抠图
                no_bg = remove_background(original_image)
                # 加白底
                with_white = add_white_background(no_bg)
                # 裁剪
                cropped = crop_non_white_content(with_white)
                
                # 保存处理后的图片
                processed_filename = get_simple_filename(clothing_type)
                processed_path = os.path.join(settings.TEMP_DIR, processed_filename)
                cropped.save(processed_path)
                
                # 上传到MyCloset目录
                logger.info(f"开始上传处理后的图片: {processed_filename}")
                if safe_seafile_upload_file(processed_path, settings.SEAFILE_CLOSET_DIR):
                    logger.info("图片上传成功，开始更新JSON文件")
                    
                    # 更新closet.json
                    closet_data = load_closet_json()
                    closet_data[processed_filename] = {
                        'type': clothing_type,
                        'features': features,
                        'upload_time': time.time()
                    }
                    
                    if save_closet_json(closet_data):
                        logger.info("JSON文件更新成功")
                        
                        # 清理临时文件
                        if os.path.exists(temp_path):
                            os.remove(temp_path)
                        if os.path.exists(processed_path):
                            os.remove(processed_path)
                        
                        # 自动生成搭配推荐
                        try:
                            auto_generate_outfit_after_upload(processed_filename)
                        except Exception as e:
                            logger.warning(f"自动生成搭配推荐失败: {e}")
                        
                        # 映射分类到closet页面分类
                        closet_category = map_classification_to_category(clothing_type)
                        
                        return JsonResponse({
                            'success': True, 
                            'label': clothing_type,
                            'features': features,
                            'filename': processed_filename,
                            'closet_category': closet_category,
                            'message': '衣物上传并分类成功'
                        })
                    else:
                        logger.error("JSON文件更新失败")
                        return JsonResponse({'success': False, 'error': '保存衣物信息失败'})
                else:
                    logger.error("图片上传到衣柜失败")
                    return JsonResponse({'success': False, 'error': '上传到衣柜失败'})
            else:
                logger.error("图片处理失败")
                return JsonResponse({'success': False, 'error': '图片处理失败'})
                
        except Exception as e:
            logger.error(f"分类过程出错: {e}")
            return JsonResponse({'success': False, 'error': f'分类过程出错: {str(e)}'})
    
    return JsonResponse({'success': False, 'error': '只支持 POST'})

def get_used_numbers_for_type(type_name):
    """
    获取指定类型的所有已使用编号
    """
    used_numbers = set()
    try:
        closet_data = load_closet_json()
        for filename in closet_data.keys():
            # 匹配格式：TYPE-NUMBER.ext
            match = re.match(rf'^{re.escape(type_name)}-(\d+)', filename)
            if match:
                used_numbers.add(int(match.group(1)))
    except Exception as e:
        logger.warning(f"获取已使用编号失败: {e}")
    return used_numbers

def validate_garment_id_uniqueness(garment_id):
    """
    验证衣物ID的唯一性
    """
    try:
        # 提取类型和编号
        match = re.match(r'^([A-Z\-]+)-(\d+)', garment_id)
        if not match:
            return False, "ID格式不正确"
        
        garment_type = match.group(1)
        garment_number = int(match.group(2))
        
        # 获取该类型的所有已使用编号
        used_numbers = get_used_numbers_for_type(garment_type)
        
        # 检查编号是否已存在
        if garment_number in used_numbers:
            return False, f"编号 {garment_number} 已被使用"
        
        return True, "ID唯一性验证通过"
        
    except Exception as e:
        return False, f"验证失败: {str(e)}"

def test_garment_numbering_system(request):
    """
    测试衣物编号系统的正确性
    """
    test_cases = [
        ("T-SHIRT", "T恤"),
        ("COAT", "外套"),
        ("DRESS", "连衣裙"),
        ("TROUSERS", "长裤"),
        ("SHIRT", "衬衫")
    ]
    
    results = []
    
    for type_name, display_name in test_cases:
        # 获取当前已使用的编号
        used_numbers = get_used_numbers_for_type(type_name)
        
        # 生成新的编号
        new_id = get_next_id(type_name)
        
        # 验证唯一性
        is_unique, message = validate_garment_id_uniqueness(new_id)
        
        result = {
            'type': type_name,
            'display_name': display_name,
            'used_numbers': sorted(list(used_numbers)),
            'new_id': new_id,
            'is_unique': is_unique,
            'message': message
        }
        results.append(result)
    
    return JsonResponse({
        'test_results': results,
        'summary': {
            'total_tests': len(results),
            'unique_ids': sum(1 for r in results if r['is_unique']),
            'conflicts': sum(1 for r in results if not r['is_unique'])
        }
    })

def responsive_test(request):
    """响应式设计测试页面"""
    return render(request, 'closet_app/responsive_test.html')

def get_next_id(label):
    """
    生成唯一的衣物ID，格式：T-SHIRT-001
    使用智能编号算法，避免删除后的撞编号问题
    """
    if not label:
        label = 'UNKNOWN'
    
    # 清理和标准化标签
    label_clean = str(label).strip().upper()
    label_clean = re.sub(r'\b(CONTENT|CATEGORY|TYPE|CLASS)\b', '', label_clean, flags=re.IGNORECASE)
    label_clean = re.sub(r'[^\w\-]', '-', label_clean)
    label_clean = re.sub(r'-+', '-', label_clean)
    label_clean = label_clean.strip('-')
    
    if not label_clean:
        label_clean = 'UNKNOWN'
    
    # 获取当前标签的所有已使用编号
    used_numbers = get_used_numbers_for_type(label_clean)
    
    # 找到最小的未使用编号
    next_number = 1
    while next_number in used_numbers:
        next_number += 1
    
    # 生成ID（不包含扩展名）
    garment_id = f"{label_clean}-{next_number:03d}"
    
    # 验证唯一性
    is_unique, message = validate_garment_id_uniqueness(garment_id)
    if not is_unique:
        logger.error(f"生成的ID不唯一: {garment_id}, 原因: {message}")
        # 如果验证失败，尝试下一个编号
        next_number += 1
        while next_number in used_numbers:
            next_number += 1
        garment_id = f"{label_clean}-{next_number:03d}"
        logger.info(f"重新生成ID: {garment_id}")
    
    logger.info(f"生成衣物ID: {label} -> {garment_id}")
    return garment_id

def load_remarks():
    if os.path.exists(REMARKS_PATH):
        with open(REMARKS_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_remarks(remarks):
    with open(REMARKS_PATH, 'w', encoding='utf-8') as f:
        json.dump(remarks, f, ensure_ascii=False, indent=2)

@csrf_exempt
def save_closet_image(request):
    if request.method == 'POST':
        image = request.FILES.get('image')
        label = request.POST.get('label', 'unknown')
        filename = f"{label}_{int(time.time())}.jpg"
        remote_path = settings.SEAFILE_CLOSET_DIR
        # 上传到Seafile
        image.seek(0)
        success = seafile_upload(image, remote_path)
        if success:
            file_path = remote_path + filename
            url = seafile_download_url(file_path)
            return JsonResponse({'success': True, 'url': url, 'filename': filename})
        else:
            return JsonResponse({'success': False, 'error': '上传失败'})
    return JsonResponse({'success': False, 'error': '仅支持POST'})

@csrf_exempt
def closet_list(request):
    try:
        # 从云端获取衣柜列表
        dir_path = settings.SEAFILE_CLOSET_DIR
        files = safe_seafile_list(dir_path)
        closet = []
        
        # 加载衣柜JSON数据
        closet_data = load_closet_json()
        
        # 过滤图片文件
        image_files = filter_files_by_type(files, 'file', ['.jpg', '.jpeg', '.png'])
        
        for f in image_files:
            file_path = dir_path + f['name']
            url = safe_seafile_download_url(file_path)
            if url:
                # 获取备注信息
                remark = ''
                if f['name'] in closet_data:
                    remark = closet_data[f['name']].get('features', '')
                
                closet.append({
                    'url': url, 
                    'filename': f['name'], 
                    'id': f['name'],
                    'remark': remark
                })
        
        return JsonResponse({'closet': closet})
    except Exception as e:
        logger.error(f"获取衣柜列表失败: {e}")
        return JsonResponse({'closet': [], 'error': str(e)})

@csrf_exempt
def closet_rename(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            img_id = data.get('id')
            remark = data.get('remark')
            
            closet_data = load_closet_json()
            if img_id in closet_data:
                closet_data[img_id]['features'] = remark
                if safe_save_closet_json(closet_data):
                    return JsonResponse({'success': True})
                else:
                    return JsonResponse({'success': False, 'error': '保存失败'})
            else:
                return JsonResponse({'success': False, 'error': '未找到该衣物'})
        except Exception as e:
            logger.error(f"修改衣物备注失败: {e}")
            return JsonResponse({'success': False, 'error': f'修改失败: {str(e)}'})
    
    return JsonResponse({'success': False, 'error': '只支持 POST'})

@csrf_exempt
def closet_delete(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            file_id = data.get('id')
            
            if not file_id:
                return JsonResponse({'success': False, 'error': '缺少文件ID'})
            
            logger.info(f"开始删除衣物: {file_id}")
            
            # 1. 删除Seafile中的图片文件
            file_path = settings.SEAFILE_CLOSET_DIR + file_id
            file_deleted = safe_seafile_delete(file_path)
            
            if not file_deleted:
                logger.error(f"删除图片文件失败: {file_path}")
                return JsonResponse({'success': False, 'error': '删除图片文件失败'})
            
            # 2. 从JSON文件中删除对应的记录
            closet_data = load_closet_json()
            json_updated = False
            
            if file_id in closet_data:
                # 删除JSON中的记录
                del closet_data[file_id]
                json_updated = safe_save_closet_json(closet_data)
                logger.info(f"从JSON中删除记录: {file_id}")
            else:
                # 如果JSON中没有记录，也视为成功（可能是历史遗留问题）
                logger.warning(f"JSON中未找到记录: {file_id}")
                json_updated = True
            
            # 3. 删除本地recoms目录下的对应文件
            try:
                # 去掉文件扩展名，获取纯文件名
                garment_name = os.path.splitext(file_id)[0]
                recoms_dir = os.path.join(settings.BASE_DIR, 'static', 'recoms')
                garment_dir = os.path.join(recoms_dir, garment_name)
                
                logger.info(f"检查本地目录: {garment_dir}")
                
                if os.path.exists(garment_dir):
                    # 删除整个目录及其内容
                    shutil.rmtree(garment_dir)
                    logger.info(f"成功删除本地目录: {garment_dir}")
                else:
                    logger.info(f"本地目录不存在，无需删除: {garment_dir}")
                    
            except Exception as e:
                logger.warning(f"删除本地文件失败: {str(e)}")
                # 本地文件删除失败不影响整体删除操作的成功
                # 因为云端文件和JSON记录已经删除成功
            
            if json_updated:
                # 记录删除的衣物信息，用于调试编号问题
                try:
                    # 提取衣物类型和编号
                    match = re.match(r'^([A-Z\-]+)-(\d+)', file_id)
                    if match:
                        garment_type = match.group(1)
                        garment_number = int(match.group(2))
                        logger.info(f"删除衣物类型: {garment_type}, 编号: {garment_number}")
                        
                        # 验证删除后的编号状态
                        remaining_numbers = get_used_numbers_for_type(garment_type)
                        logger.info(f"删除后 {garment_type} 类型的剩余编号: {sorted(remaining_numbers)}")
                except Exception as e:
                    logger.warning(f"记录删除信息失败: {e}")
                
                logger.info(f"衣物删除成功: {file_id}")
                return JsonResponse({
                    'success': True, 
                    'message': '衣物删除成功',
                    'deleted_file': file_id
                })
            else:
                logger.error(f"更新JSON文件失败: {file_id}")
                return JsonResponse({
                    'success': False, 
                    'error': '删除成功但更新记录失败，请刷新页面'
                })
                
        except Exception as e:
            logger.error(f"删除衣物失败: {e}")
            return JsonResponse({
                'success': False, 
                'error': f'删除失败: {str(e)}'
            })
    
    return JsonResponse({'success': False, 'error': '仅支持POST'})

def classify_image(image_file):
    """
    调用服务器分类接口（通过ssh隧道，端口8899），返回分类标签。
    """
    url = "http://127.0.0.1:8899/api/classify/"  # 通过ssh隧道映射到服务器8877端口
    files = {'image': image_file}
    try:
        response = requests.post(url, files=files, timeout=30)
        if response.status_code == 200:
            result = response.json()
            # 假设返回格式为 {'label': 'xxx'}
            return result.get('label')
        else:
            logger.error(f"分类请求失败，状态码：{response.status_code}, 错误信息：{response.text}")
            return None
    except requests.exceptions.ConnectionError:
        logger.error("无法连接到分类服务器，请检查服务器是否运行")
        return None
    except requests.exceptions.Timeout:
        logger.error("分类请求超时")
        return None
    except Exception as e:
        logger.error(f"分类请求出错: {str(e)}")
        return None

def load_body_remarks():
    if os.path.exists(BODY_REMARKS_PATH):
        with open(BODY_REMARKS_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_body_remarks(remarks):
    with open(BODY_REMARKS_PATH, 'w', encoding='utf-8') as f:
        json.dump(remarks, f, ensure_ascii=False, indent=2)

@csrf_exempt
def body_list(request):
    if request.method == 'GET':
        try:
            dir_path = settings.SEAFILE_BODY_DIR
            files = safe_seafile_list(dir_path)
            body_data = load_body_json()
            body = []
            
            # 过滤图片文件
            image_files = filter_files_by_type(files, 'file', ['.jpg', '.jpeg', '.png'])
            
            for f in image_files:
                # 处理文件名，移除扩展名作为ID
                filename = f['name']
                img_id = filename
                for ext in ['.jpg', '.jpeg', '.png']:
                    if filename.endswith(ext):
                        img_id = filename[:-len(ext)]
                        break
                
                file_path = dir_path + filename
                url = safe_seafile_download_url(file_path)
                if url:
                    # 获取备注信息
                    remark = ''
                    if img_id in body_data:
                        remark = body_data[img_id].get('remark', '')
                    
                    body.append({
                        'id': img_id,
                        'filename': filename,
                        'url': url,
                        'remark': remark
                    })
            
            return JsonResponse({'body': body})
        except Exception as e:
            logger.error(f"获取身体列表失败: {e}")
            return JsonResponse({'body': [], 'error': str(e)})
    
    return JsonResponse({'body': []})

@csrf_exempt
def save_body_image(request):
    if request.method == 'POST':
        image_file = request.FILES.get('image')
        if not image_file:
            return JsonResponse({'success': False, 'error': '缺少图片'})
        
        try:
            # 生成唯一ID
            dir_path = settings.SEAFILE_BODY_DIR
            files = safe_seafile_list(dir_path)
            
            # 计算文件数量
            file_count = get_file_count_by_type(files, 'file')
            img_id = f"pose-{file_count+1:03d}"
            filename = f"{img_id}.jpg"
            
            # 保存图片到本地临时目录
            temp_path = os.path.join(settings.TEMP_DIR, filename)
            with open(temp_path, 'wb') as f:
                for chunk in image_file.chunks():
                    f.write(chunk)
            
            # 上传到Seafile
            if safe_seafile_upload_file(temp_path, dir_path):
                file_path = dir_path + filename
                url = safe_seafile_download_url(file_path)
                
                # 更新body.json
                body_data = load_body_json()
                body_data[img_id] = {
                    'filename': filename,
                    'upload_time': time.time(),
                    'remark': ''
                }
                save_body_json(body_data)
                
                # 清理临时文件
                os.remove(temp_path)
                
                return JsonResponse({
                    'success': True, 
                    'filename': filename, 
                    'id': img_id, 
                    'url': url
                })
            else:
                return JsonResponse({'success': False, 'error': '上传失败'})
                
        except Exception as e:
            logger.error(f"保存身体图片失败: {e}")
            return JsonResponse({'success': False, 'error': f'保存失败: {str(e)}'})
    
    return JsonResponse({'success': False, 'error': '只支持 POST'})

@csrf_exempt
def body_rename(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            img_id = data.get('id')
            remark = data.get('remark')
            
            body_data = load_body_json()
            if img_id in body_data:
                body_data[img_id]['remark'] = remark
                if save_body_json(body_data):
                    return JsonResponse({'success': True})
                else:
                    return JsonResponse({'success': False, 'error': '保存失败'})
            else:
                return JsonResponse({'success': False, 'error': '未找到该姿态照片'})
        except Exception as e:
            logger.error(f"修改身体备注失败: {e}")
            return JsonResponse({'success': False, 'error': f'修改失败: {str(e)}'})
    
    return JsonResponse({'success': False, 'error': '只支持 POST'})

@csrf_exempt
def test_classify(request):
    """测试分类功能的视图"""
    if request.method == 'POST':
        # 创建一个测试图片文件
        from PIL import Image
        import io
        
        # 创建一个简单的测试图片
        img = Image.new('RGB', (100, 100), color='red')
        img_io = io.BytesIO()
        img.save(img_io, format='JPEG')
        img_io.seek(0)
        
        # 模拟文件上传
        from django.core.files.uploadedfile import SimpleUploadedFile
        test_file = SimpleUploadedFile(
            "test.jpg",
            img_io.getvalue(),
            content_type="image/jpeg"
        )
        
        # 调用分类函数
        label = classify_image(test_file)
        if label:
            return JsonResponse({'success': True, 'label': label, 'message': '测试分类成功'})
        else:
            return JsonResponse({'success': False, 'error': '测试分类失败'})
    
    return JsonResponse({'success': False, 'error': '只支持 POST'})

def seafile_headers():
    return {'Authorization': f'Token {settings.SEAFILE_TOKEN}'}

def seafile_upload(file, remote_path):
    # 获取上传链接
    url = f"{settings.SEAFILE_API_URL}/repos/{settings.SEAFILE_LIBRARY_ID}/upload-link/"
    resp = requests.get(url, headers=seafile_headers())
    upload_link = resp.json()
    # 上传文件
    files = {'file': (file.name, file.read())}
    data = {'parent_dir': remote_path}
    resp = requests.post(upload_link, data=data, files=files)
    return resp.status_code == 200

def seafile_list(dir_path):
    url = f"{settings.SEAFILE_API_URL}/repos/{settings.SEAFILE_LIBRARY_ID}/dir/"
    params = {'p': dir_path}
    resp = requests.get(url, headers=seafile_headers(), params=params)
    if resp.status_code == 200:
        return resp.json().get('dirent_list', [])
    return []

def seafile_delete(file_path):
    url = f"{settings.SEAFILE_API_URL}/repos/{settings.SEAFILE_LIBRARY_ID}/file/"
    params = {'p': file_path}
    resp = requests.delete(url, headers=seafile_headers(), params=params)
    return resp.status_code == 200

def seafile_download_url(file_path):
    # 获取下载直链
    url = f"{settings.SEAFILE_API_URL}/repos/{settings.SEAFILE_LIBRARY_ID}/file/"
    params = {'p': file_path}
    resp = requests.get(url, headers=seafile_headers(), params=params)
    if resp.status_code == 200:
        return resp.json().get('url')
    return None
#通过coze获取天气
#personal_access_token = 'pat_rOYu6mJk8jn7XYLMJbiTVkQ2deE4mqJVMGrMcPsGpZp0BETa7yYz38ne9r5W8GRM'
#coze_api_base = 'https://api.coze.cn'
#workflow_id = '7527249757652549641'

def get_weather(request):
    if request.method == 'GET':
        city = request.GET.get('city')
        print(f"=== get_weather 函数被调用，城市参数: {city} ===")
        if city:
            print(f"=== 开始调用云平台获取天气信息，城市: {city} ===")
            coze = Coze(auth=TokenAuth(token=settings.COZE_TOKEN), base_url=settings.COZE_API_BASE)
            try:
                stream = coze.workflows.runs.stream(
                    workflow_id=settings.COZE_WEATHER_WORKFLOW_ID,
                    parameters={"city": city}
                )
                weather_info_list = []
                has_messages = False

                for event in stream:
                    has_messages = True
                    print(f"=== 接收到事件类型: {event.event} ===")
                    if event.event == WorkflowEventType.MESSAGE:
                        try:
                            # 安全地获取消息内容
                            if event.message is not None:
                                if hasattr(event.message, 'content') and event.message.content is not None:
                                    content = event.message.content
                                else:
                                    content = str(event.message)
                            else:
                                content = "无消息内容"
                            
                            print(f"=== 从云平台获取到的天气原始信息 ===")
                            print(f"原始内容: {content}")
                            print(f"=== 原始信息结束 ===")
                            
                            # 确保content是字符串类型
                            if not isinstance(content, str):
                                logger.error(f"内容类型错误，期望字符串，实际是: {type(content).__name__}")
                                continue
                            
                            data = json.loads(content)
                            print(f"=== 解析后的JSON数据 ===")
                            print(f"JSON数据: {json.dumps(data, ensure_ascii=False, indent=2)}")
                            print(f"=== JSON数据结束 ===")
                            
                            # 使用测试代码中验证过的'date'字段
                            weather_list = data.get("date", [])
                            if not weather_list:
                                logger.warning("返回的天气列表为空")
                                continue
                            
                            # 处理当天天气信息并调用Coze智能体
                            if weather_list and len(weather_list) > 0:
                                today_weather = weather_list[0]  # 获取第一天的天气（当天）
                                print(f"=== 当天天气信息 ===")
                                print(f"日期: {today_weather.get('predict_date', '未知')}")
                                print(f"天气状况: {today_weather.get('condition', '未知')}")
                                print(f"最高温度: {today_weather.get('temp_high', '未知')}°C")
                                print(f"最低温度: {today_weather.get('temp_low', '未知')}°C")
                                print(f"=== 当天天气信息结束 ===")
                                
                                # 将当天天气信息转换为字符串格式
                                today_weather_str = json.dumps(today_weather, ensure_ascii=False)
                                print(f"=== 当天天气信息字符串: {today_weather_str} ===")
                                
                                # 获取closet.json内容
                                try:
                                    closet_data = load_closet_json()
                                    closet_json_str = json.dumps(closet_data, ensure_ascii=False)
                                    print(f"=== 衣柜信息字符串长度: {len(closet_json_str)} ===")
                                    
                                    # 调用Coze智能体获取搭配推荐
                                    recommended_garment = call_coze_matching_recommendation(today_weather_str, closet_json_str)
                                    if recommended_garment:
                                        print(f"=== 获取到推荐上衣: {recommended_garment} ===")
                                    else:
                                        print(f"=== 未获取到推荐上衣 ===")
                                        
                                except Exception as e:
                                    print(f"获取衣柜信息失败: {str(e)}")
                            
                            # 处理所有天气信息用于返回
                            for weather in weather_list:
                                # 确保所有需要的字段都存在
                                required_fields = ["condition", "predict_date", "temp_high", "temp_low"]
                                for field in required_fields:
                                    if field not in weather:
                                        logger.warning(f"天气数据缺少必要字段: {field}")
                                        # 跳过不完整的数据
                                        continue
                                
                                weather_info = {
                                    'date': weather["predict_date"],
                                    'condition': weather["condition"],
                                    'temp_high': weather["temp_high"],
                                    'temp_low': weather["temp_low"]
                                }
                                weather_info_list.append(weather_info)
                                
                        except json.JSONDecodeError as e:
                            print(f"=== JSON解析失败 ===")
                            print(f"错误信息: {str(e)}")
                            print(f"原始内容: {content}")
                            print(f"=== JSON解析失败结束 ===")
                            logger.error(f"JSON 解析失败，原始内容: {content[:200]}...，错误信息: {str(e)}")
                            # 调试用：打印完整内容
                            logger.debug(f"完整原始内容: {content}")
                        except AttributeError as e:
                            print(f"=== 属性错误 ===")
                            print(f"错误信息: {str(e)}")
                            print(f"event结构: {dir(event)}")
                            print(f"=== 属性错误结束 ===")
                            logger.error(f"属性错误: {str(e)}，event结构: {dir(event)}")
                        except Exception as e:
                            print(f"=== 处理消息时发生未知错误 ===")
                            print(f"错误信息: {str(e)}")
                            print(f"=== 未知错误结束 ===")
                            logger.error(f"处理消息时发生未知错误: {str(e)}")
                    elif event.event == WorkflowEventType.ERROR:
                        print(f"=== 云平台返回错误 ===")
                        print(f"错误内容: {event.error}")
                        print(f"=== 云平台错误结束 ===")
                        logger.error(f"调用出错: {event.error}")
                        return JsonResponse({'error': f'API调用错误: {event.error}'}, status=500)

                # 只取前五天的天气信息
                weather_info_list = weather_info_list[:5]
                print(f"=== 最终处理的天气信息列表 ===")
                print(f"天气信息: {json.dumps(weather_info_list, ensure_ascii=False, indent=2)}")
                print(f"=== 天气信息列表结束 ===")

                if weather_info_list:
                    return JsonResponse({'weather_info_list': weather_info_list}, safe=False)
                else:
                    if not has_messages:
                        print(f"=== 未接收到任何消息事件 ===")
                        logger.error("未接收到任何消息事件")
                        return JsonResponse({'error': '未从API接收到任何数据'}, status=500)
                    else:
                        print(f"=== 未获取到有效的天气信息 ===")
                        logger.warning("未获取到有效的天气信息")
                        return JsonResponse({'error': '未能解析天气信息，请检查城市名称是否正确'}, status=400)
            except Exception as e:
                print(f"=== 请求过程中发生错误 ===")
                print(f"错误信息: {str(e)}")
                print(f"=== 请求错误结束 ===")
                logger.error(f"请求过程中发生错误: {str(e)}")
                return JsonResponse({'error': f'请求处理失败: {str(e)}'}, status=500)
        else:
            print(f"=== 未提供城市参数 ===")
            return JsonResponse({'error': '未提供城市参数'}, status=400)
    else:
        print(f"=== 不支持的请求方法: {request.method} ===")
        return JsonResponse({'error': '仅支持 GET 请求'}, status=405)

#通过coze调用获取搭配
def coze_workflow(request):
    if request.method == 'POST':
        print("=== 开始处理 coze_workflow 请求 ===")
        
        # 获取前端传递的参数
        city = request.POST.get('city')
        end_time = request.POST.get('end_time')
        gender = request.POST.get('gender')
        height = request.POST.get('height')
        start_time = request.POST.get('start_time')
        weight = request.POST.get('weight')
        wendang = request.POST.get('wendang')
        scene = request.POST.get('scene')  # 新增场景信息

        print(f"=== 接收到的参数 ===")
        print(f"city: {city}")
        print(f"end_time: {end_time}")
        print(f"gender: {gender}")
        print(f"height: {height}")
        print(f"start_time: {start_time}")
        print(f"weight: {weight}")
        print(f"wendang: {wendang}")
        print(f"scene: {scene}")

        # 检查 height 是否为空或无效
        if not height or not height.isdigit():
            print(f"=== 身高参数无效: {height} ===")
            return JsonResponse({'error': '身高参数无效，请提供有效的整数身高值'}, status=400)

        try:
            height = int(height)
            print(f"=== 身高转换成功: {height} ===")
        except ValueError:
            print(f"=== 身高转换失败: {height} ===")
            return JsonResponse({'error': '身高参数无法转换为整数，请提供有效的整数身高值'}, status=400)

        # 获取 closet.json 的内容作为文本字符串
        print("=== 开始获取 closet.json 内容 ===")
        closet_json_path = settings.SEAFILE_CLOSET_DIR + 'closet.json'
        print(f"closet.json 路径: {closet_json_path}")
        
        # 读取closet.json的内容
        closet_data = seafile_read_json(closet_json_path)
        if closet_data:
            print(f"=== 成功读取 closet.json 内容 ===")
            print(f"=== closet.json 原始数据: {closet_data} ===")
            # 将JSON数据转换为字符串格式
            wendang = json.dumps(closet_data, ensure_ascii=False, indent=2)
            print(f"=== closet.json 内容长度: {len(wendang)} 字符 ===")
            print(f"=== closet.json 字符串内容前200字符: {wendang[:200]}... ===")
        else:
            print(f"=== 获取 closet.json 内容失败 ===")
            # 如果获取失败，使用前端传递的 wendang（如果有的话）
            if not wendang:
                print(f"=== 前端也未提供 wendang，将使用空字符串 ===")
                wendang = ""

        print(f"=== 最终使用的 wendang: {wendang} ===")

        # 验证其他必要参数
        if not city:
            print(f"=== 城市参数为空 ===")
            return JsonResponse({'error': '城市参数不能为空'}, status=400)
        
        if not gender:
            print(f"=== 性别参数为空 ===")
            return JsonResponse({'error': '性别参数不能为空'}, status=400)

        print("=== 开始调用 Coze 智能体 ===")
        coze = Coze(auth=TokenAuth(token=settings.COZE_TOKEN), base_url=settings.COZE_API_BASE)

        # 准备传递给 Coze 的参数
        coze_parameters = {
            "city": city,
            "end_time": end_time,
            "gender": gender,
            "height": height,
            "start_time": start_time,
            "weight": weight,
            "wendang": wendang,
            "scene": scene
        }
        
        print(f"=== 传递给 Coze 的参数 ===")
        for key, value in coze_parameters.items():
            print(f"{key}: {value}")

        try:
            stream = coze.workflows.runs.stream(
                workflow_id=settings.COZE_OUTFIT_WORKFLOW_ID,
                parameters=coze_parameters
            )

            print("=== 开始接收 Coze 响应 ===")
            results = []
            message_count = 0
            error_count = 0
            
            for event in stream:
                print(f"=== 接收到事件类型: {event.event} ===")
                
                if event.event == WorkflowEventType.MESSAGE:
                    message_count += 1
                    print(f"=== 接收到第 {message_count} 条消息 ===")
                    print(f"消息内容: {event.message}")
                    results.append(event.message)
                elif event.event == WorkflowEventType.ERROR:
                    error_count += 1
                    print(f"=== 接收到第 {error_count} 个错误 ===")
                    print(f"错误内容: {event.error}")
                    return JsonResponse({'error': event.error}, status=500)

            print(f"=== Coze 响应处理完成 ===")
            print(f"总消息数: {message_count}")
            print(f"总错误数: {error_count}")
            print(f"返回结果: {results}")

            # 将WorkflowEventMessage对象转换为可序列化的格式
            serializable_results = []
            for result in results:
                if hasattr(result, 'content'):
                    serializable_results.append(str(result.content))
                else:
                    serializable_results.append(str(result))
            
            print(f"=== 序列化后的结果: {serializable_results} ===")
            
            # 解析Coze输出并处理图片拼接
            if serializable_results:
                try:
                    # 解析第一个结果（通常只有一个结果）
                    result_str = serializable_results[0]
                    print(f"=== 解析结果字符串: {result_str} ===")
                    
                    # 解析JSON格式的输出
                    result_data = json.loads(result_str)
                    output_text = result_data.get('output', '')
                    print(f"=== 提取的output字段: {output_text} ===")
                    
                    if output_text:
                        # 预处理：处理换行符和特殊字符
                        output_text = output_text.replace('\\n', '\n').replace('\\t', '\t')
                        print(f"=== 预处理后的output_text: {output_text} ===")
                        
                        # 使用智能分割逻辑，支持多种分隔符
                        clothing_items = []
                        
                        # 首先尝试按换行符分割
                        if '\n' in output_text:
                            print(f"=== 检测到换行符分隔 ===")
                            parts = output_text.split('\n')
                            print(f"换行符分割后的部分: {parts}")
                            
                            for part in parts:
                                part = part.strip()
                                if part:
                                    clothing_items.append(part)
                        
                        # 如果没有换行符，尝试按分号分割
                        elif ';' in output_text or '；' in output_text:
                            print(f"=== 检测到分号分隔 ===")
                            if '；' in output_text:
                                parts = output_text.split('；')
                                print(f"使用中文分号分割")
                            else:
                                parts = output_text.split(';')
                                print(f"使用英文分号分割")
                            print(f"分号分割后的部分: {parts}")
                            
                            for part in parts:
                                part = part.strip()
                                if part:
                                    clothing_items.append(part)
                        
                        # 如果没有分号，尝试按中文逗号分割
                        elif '，' in output_text:
                            print(f"=== 检测到中文逗号分隔 ===")
                            parts = output_text.split('，')
                            print(f"中文逗号分割后的部分: {parts}")
                            
                            for part in parts:
                                part = part.strip()
                                if part:
                                    clothing_items.append(part)
                        
                        # 如果都没有，尝试按英文逗号分割
                        elif ',' in output_text:
                            print(f"=== 检测到英文逗号分隔 ===")
                            parts = output_text.split(',')
                            print(f"英文逗号分割后的部分: {parts}")
                            
                            for part in parts:
                                part = part.strip()
                                if part:
                                    clothing_items.append(part)
                        
                        elif '+' in output_text:
                            print(f"=== 检测到加号分隔 ===")
                            parts = output_text.split('+')
                            print(f"加号分割后的部分: {parts}")
                            
                            for part in parts:
                                part = part.strip()
                                if part:
                                    clothing_items.append(part)
                        
                        # 如果都没有，尝试直接解析整个字符串
                        else:
                            print(f"=== 尝试直接解析整个字符串 ===")
                            if output_text.strip():
                                clothing_items.append(output_text.strip())
                        
                        print(f"=== 最终分割后的衣物项目: {clothing_items} ===")
                        
                        if len(clothing_items) >= 2:
                            # 获取前两个衣物项目
                            top_item = clothing_items[0]  # 上方图片
                            bottom_item = clothing_items[1]  # 下方图片
                            
                            print(f"=== 原始上方衣物: {top_item} ===")
                            print(f"=== 原始下方衣物: {bottom_item} ===")
                            
                            # 使用extract_garment_name和clean_garment_filename函数处理衣物名称
                            processed_items = []
                            
                            for item in [top_item, bottom_item]:
                                print(f"=== 处理衣物名称: {item} ===")
                                
                                # 使用extract_garment_name提取衣物名称
                                extracted_name = extract_garment_name(item)
                                print(f"=== 提取后的名称: {extracted_name} ===")
                                
                                if extracted_name:
                                    # 使用clean_garment_filename清理文件名
                                    cleaned_name = clean_garment_filename(extracted_name)
                                    print(f"=== 清理后的文件名: {cleaned_name} ===")
                                    
                                    if cleaned_name:
                                        processed_items.append(cleaned_name)
                                    else:
                                        print(f"=== 文件名清理失败，使用原始名称: {item} ===")
                                        processed_items.append(item)
                                else:
                                    print(f"=== 名称提取失败，使用原始名称: {item} ===")
                                    processed_items.append(item)
                            
                            if len(processed_items) >= 2:
                                top_item = processed_items[0]
                                bottom_item = processed_items[1]
                                
                                print(f"=== 处理后的上方衣物: {top_item} ===")
                                print(f"=== 处理后的下方衣物: {bottom_item} ===")
                                
                                # 下载并处理图片
                                processed_images = []
                                
                                for item in [top_item, bottom_item]:
                                    # 构造文件名（添加.jpg扩展名）
                                    filename = f"{item}.jpg"
                                    file_path = settings.SEAFILE_CLOSET_DIR + filename
                                    
                                    print(f"=== 尝试获取图片: {file_path} ===")
                                    
                                    # 获取图片
                                    original_image = seafile_access_image(file_path)
                                    if original_image:
                                        print(f"=== 成功获取图片: {filename} ===")
                                        
                                        # 处理图片：抠图 -> 加白底 -> 裁剪
                                        try:
                                            no_bg = remove_background(original_image)
                                            with_white = add_white_background(no_bg)
                                            cropped = crop_non_white_content(with_white)
                                            
                                            processed_images.append(cropped)
                                            print(f"=== 图片处理完成: {filename} ===")
                                        except Exception as e:
                                            print(f"=== 图片处理失败: {filename}, 错误: {e} ===")
                                            # 如果处理失败，创建一个占位图
                                            placeholder = Image.new('RGB', (200, 200), (200, 200, 200))
                                            processed_images.append(placeholder)
                                    else:
                                        print(f"=== 无法获取图片: {filename} ===")
                                        # 如果无法获取图片，创建一个占位图
                                        placeholder = Image.new('RGB', (200, 200), (200, 200, 200))
                                        processed_images.append(placeholder)
                                
                                print(f"=== 处理后的图片数量: {len(processed_images)} ===")
                                
                                # 拼接图片
                                if len(processed_images) >= 2:
                                    print(f"=== 开始拼接图片 ===")
                                    combined_image = concat_images_vertically(processed_images[0], processed_images[1])
                                    
                                    # 生成协调图片文件名
                                    coord_filename = f"coord-{int(time.time())}.jpg"
                                    coord_path = os.path.join(settings.TEMP_DIR, coord_filename)
                                    
                                    # 保存拼接后的图片
                                    combined_image.save(coord_path)
                                    print(f"=== 拼接图片已保存: {coord_path} ===")
                                    
                                    # 上传到MyCoord目录
                                    if safe_seafile_upload_file(coord_path, settings.SEAFILE_COORD_DIR):
                                        print(f"=== 拼接图片上传成功: {coord_filename} ===")
                                        
                                        # 获取上传后的下载链接
                                        coord_file_path = settings.SEAFILE_COORD_DIR + coord_filename
                                        coord_url = safe_seafile_download_url(coord_file_path)
                                        
                                        # 清理临时文件
                                        if os.path.exists(coord_path):
                                            os.remove(coord_path)
                                        
                                        return JsonResponse({
                                            'success': True,
                                            'results': serializable_results,
                                            'coord_image': coord_filename,
                                            'coord_url': coord_url,
                                            'message': '搭配推荐生成成功'
                                        })
                                    else:
                                        print(f"=== 拼接图片上传失败 ===")
                                        return JsonResponse({
                                            'success': False,
                                            'results': serializable_results,
                                            'error': '拼接图片上传失败'
                                        })
                                else:
                                    print(f"=== 处理后的图片数量不足: {len(processed_images)} ===")
                                    return JsonResponse({
                                        'success': False,
                                        'results': serializable_results,
                                        'error': '图片处理失败'
                                    })
                        else:
                            print(f"=== 衣物项目数量不足: {len(clothing_items)} ===")
                            return JsonResponse({
                                'success': False,
                                'results': serializable_results,
                                'error': '搭配推荐格式不正确'
                            })
                    else:
                        print(f"=== 未找到output字段 ===")
                        return JsonResponse({
                            'success': False,
                            'results': serializable_results,
                            'error': '未找到搭配推荐内容'
                        })
                        
                except json.JSONDecodeError as e:
                    print(f"=== JSON解析失败: {e} ===")
                    return JsonResponse({
                        'success': False,
                        'results': serializable_results,
                        'error': f'结果解析失败: {str(e)}'
                    })
                except Exception as e:
                    print(f"=== 图片处理过程出错: {e} ===")
                    return JsonResponse({
                        'success': False,
                        'results': serializable_results,
                        'error': f'图片处理失败: {str(e)}'
                    })
            
            return JsonResponse({'results': serializable_results})
            
        except Exception as e:
            print(f"=== 调用 Coze 时发生异常 ===")
            print(f"异常类型: {type(e)}")
            print(f"异常内容: {e}")
            logger.error(f"调用 Coze 智能体失败: {e}")
            return JsonResponse({'error': f'调用智能体失败: {str(e)}'}, status=500)
            
    else:
        print(f"=== 请求方法不支持: {request.method} ===")
        return JsonResponse({'error': 'Invalid request method'}, status=405)
# Create your views here.

# ========== 图像处理函数 ==========

def seafile_access_image(file_path):
    """通过token访问Seafile云盘中的图片，获取下载链接并转换为Image对象"""
    logger.info(f"尝试访问图片: {file_path}")
    
    # 检查文件是否存在
    url = f"{settings.SEAFILE_API_URL}/repos/{settings.SEAFILE_LIBRARY_ID}/file/detail/"
    params = {'p': file_path}
    resp = requests.get(url, headers=seafile_headers(), params=params)
    
    if resp.status_code == 200:
        logger.info(f"文件存在: {file_path}")
        # 获取下载链接
        download_url = safe_seafile_download_url(file_path)
        if download_url:
            # 下载图片并转换为Image对象
            try:
                response = requests.get(download_url)
                if response.status_code == 200:
                    image = Image.open(BytesIO(response.content)).convert("RGBA")
                    logger.info(f"成功加载图片: {file_path}")
                    return image
                else:
                    logger.error(f"下载图片失败: {download_url}, 状态码: {response.status_code}")
                    return None
            except Exception as e:
                logger.error(f"转换图片时出错: {e}")
                return None
        else:
            logger.error(f"获取下载链接失败: {file_path}")
            return None
    else:
        logger.error(f"文件不存在或无权限访问: {file_path}")
        return None

def remove_background(img):
    """从PIL Image对象中抠图并返回 RGBA 图像"""
    # 将Image对象转换为bytes
    img_bytes = BytesIO()
    img.save(img_bytes, format='PNG')
    input_bytes = img_bytes.getvalue()
    
    output_bytes = remove(input_bytes)  # 使用 rembg 抠图
    if isinstance(output_bytes, bytes):
        result_image = Image.open(BytesIO(output_bytes)).convert("RGBA")
    elif hasattr(output_bytes, 'convert') and not isinstance(output_bytes, np.ndarray):
        # 如果返回的是PIL Image对象，直接转换
        result_image = output_bytes.convert("RGBA")
    else:
        # 如果返回的是numpy数组，转换为PIL Image
        if isinstance(output_bytes, np.ndarray):
            result_image = Image.fromarray(output_bytes).convert("RGBA")
        else:
            # 其他情况，尝试直接转换
            result_image = Image.fromarray(output_bytes).convert("RGBA")
    return result_image

def add_white_background(image):
    """给抠图后的图像加上白色背景，输出 RGB 图像"""
    white_bg = Image.new("RGBA", image.size, (255, 255, 255, 255))
    white_bg.paste(image, mask=image)  # 使用 alpha 通道粘贴
    return white_bg.convert("RGB")

def crop_non_white_content(img, threshold=240):
    """裁剪图像上下纯白区域（RGB > threshold），适合处理抠好图但边缘有白底的情况"""
    img = img.convert("RGB")
    width, height = img.size

    top = 0
    for y in range(height):
        for x in range(width):
            r, g, b = img.getpixel((x, y))
            if r < threshold or g < threshold or b < threshold:
                top = y
                break
        else:
            continue
        break

    bottom = height - 1
    for y in reversed(range(height)):
        for x in range(width):
            r, g, b = img.getpixel((x, y))
            if r < threshold or g < threshold or b < threshold:
                bottom = y
                break
        else:
            continue
        break

    return img.crop((0, top, width, bottom + 1))

def concat_images_vertically(img1, img2):
    """垂直拼接两张图片"""
    width = max(img1.width, img2.width)
    height = img1.height + img2.height
    new_img = Image.new("RGB", (width, height), (255, 255, 255))  # 白色背景

    img1_x = (width - img1.width) // 2
    img2_x = (width - img2.width) // 2

    new_img.paste(img1, (img1_x, 0))
    new_img.paste(img2, (img2_x, img1.height))
    return new_img

# ========== Coze API调用函数 ==========

def call_coze_classify(image_url, max_retries=3, retry_delay=2):
    """调用Coze平台进行衣物分类，支持重试机制"""
    for attempt in range(max_retries):
        try:
            print(f"=== 开始调用Coze分类 (第{attempt + 1}次尝试) ===")
            print(f"图片URL: {image_url}")
            print(f"Workflow ID: {settings.COZE_CLASSIFY_WORKFLOW_ID}")
            
            stream = coze.workflows.runs.stream(
                workflow_id=settings.COZE_CLASSIFY_WORKFLOW_ID,
                parameters={"img": image_url}
            )
            
            for event in stream:
                print(f"=== Coze事件类型: {event.event} ===")
                if event.event == WorkflowEventType.MESSAGE:
                    print(f"=== Coze返回消息内容 ===")
                    print(f"消息类型: {type(event.message)}")
                    print(f"消息内容: {event.message}")
                    print(f"消息内容长度: {len(str(event.message))}")
                    print(f"消息内容repr: {repr(event.message)}")
                    logger.info(f"分类结果: {event.message}")
                    return event.message
                elif event.event == WorkflowEventType.ERROR:
                    print(f"=== Coze返回错误 ===")
                    print(f"错误内容: {event.error}")
                    logger.error(f"分类错误: {event.error}")
                    
                    # 检查是否是服务器过载错误
                    error_str = str(event.error)
                    if "server overload" in error_str.lower() or "5000" in error_str:
                        print(f"检测到服务器过载错误，将进行重试...")
                        break  # 跳出事件循环，进行重试
                    else:
                        # 其他错误，直接返回None
                        return None
                        
        except Exception as e:
            print(f"=== Coze调用异常 (第{attempt + 1}次尝试) ===")
            print(f"异常类型: {type(e)}")
            print(f"异常内容: {e}")
            logger.error(f"调用Coze分类失败: {e}")
            
            # 检查是否是网络相关错误，如果是则重试
            if "timeout" in str(e).lower() or "connection" in str(e).lower():
                print(f"检测到网络错误，将进行重试...")
            else:
                # 其他异常，直接返回None
                return None
        
        # 如果不是最后一次尝试，等待后重试
        if attempt < max_retries - 1:
            print(f"等待 {retry_delay} 秒后重试...")
            time.sleep(retry_delay)
            retry_delay *= 2  # 指数退避
    
    print(f"=== Coze分类失败，已尝试 {max_retries} 次 ===")
    logger.error(f"Coze分类失败，已尝试 {max_retries} 次")
    return None

# ========== JSON文件管理函数 ==========

def seafile_read_json(file_path):
    """
    直接从Seafile读取JSON文件内容
    使用Seafile API获取文件内容，避免下载到本地
    """
    try:
        # 获取文件下载链接
        url = safe_seafile_download_url(file_path)
        if not url:
            logger.error(f"无法获取文件下载链接: {file_path}")
            return None
        
        # 直接下载文件内容
        response = requests.get(url, timeout=30)
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"下载JSON文件失败: {file_path}, 状态码: {response.status_code}")
            return None
    except Exception as e:
        logger.error(f"读取JSON文件失败: {file_path}, 错误: {e}")
        return None

def seafile_write_json_direct(file_path, data):
    """
    直接向Seafile写入JSON文件内容（真正的云端操作）
    先删除现有文件，再上传新文件，确保覆盖
    """
    try:
        # 先删除现有文件（如果存在）
        try:
            safe_seafile_delete(file_path)
            logger.info(f"删除现有文件: {file_path}")
        except:
            # 文件不存在，忽略错误
            pass
        
        # 创建临时JSON文件
        temp_filename = f"temp_{int(time.time())}.json"
        temp_path = os.path.join(settings.TEMP_DIR, temp_filename)
        
        # 写入JSON数据
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        # 使用safe_seafile_upload_file上传到指定目录
        remote_dir = os.path.dirname(file_path)
        filename = os.path.basename(file_path)
        
        # 重命名临时文件为目标文件名
        target_temp_path = os.path.join(settings.TEMP_DIR, filename)
        os.rename(temp_path, target_temp_path)
        
        # 上传文件
        success = safe_seafile_upload_file(target_temp_path, remote_dir)
        
        # 清理临时文件
        if os.path.exists(target_temp_path):
            os.remove(target_temp_path)
        
        if success:
            logger.info(f"JSON文件直接写入成功: {file_path}")
            return True
        else:
            logger.error(f"JSON文件直接写入失败: {file_path}")
            return False
                
    except Exception as e:
        logger.error(f"直接写入JSON文件失败: {file_path}, 错误: {e}")
        # 清理临时文件
        if os.path.exists(temp_path):
            os.remove(temp_path)
        if os.path.exists(target_temp_path):
            os.remove(target_temp_path)
        return False

def seafile_ensure_json_exists(file_path, default_data=None):
    """
    确保JSON文件存在，如果不存在则创建
    """
    try:
        # 尝试读取文件
        data = seafile_read_json(file_path)
        if data is not None:
            return True
        
        # 文件不存在，创建默认文件
        if default_data is None:
            default_data = {}
        
        return seafile_write_json_direct(file_path, default_data)
        
    except Exception as e:
        logger.error(f"确保JSON文件存在失败: {file_path}, 错误: {e}")
        return False

def load_closet_json():
    """加载衣柜JSON文件"""
    try:
        file_path = settings.SEAFILE_CLOSET_DIR + 'closet.json'
        
        # 确保文件存在
        if not seafile_ensure_json_exists(file_path, {}):
            logger.error("无法确保closet.json文件存在")
            return {}
        
        # 读取JSON数据
        data = seafile_read_json(file_path)
        if data is None:
            logger.error("无法读取closet.json文件")
            return {}
        
        return data
        
    except Exception as e:
        logger.error(f"加载衣柜JSON失败: {e}")
        return {}

def save_closet_json(closet_data):
    """保存衣柜JSON文件（使用安全保存）"""
    return safe_save_closet_json(closet_data)

def load_body_json():
    """加载身体JSON文件"""
    try:
        file_path = settings.SEAFILE_BODY_DIR + 'body.json'
        
        # 确保文件存在
        if not seafile_ensure_json_exists(file_path, {}):
            logger.error("无法确保body.json文件存在")
            return {}
        
        # 读取JSON数据
        data = seafile_read_json(file_path)
        if data is None:
            logger.error("无法读取body.json文件")
            return {}
        
        return data
        
    except Exception as e:
        logger.error(f"加载身体JSON失败: {e}")
        return {}

def save_body_json(body_data):
    """保存身体JSON文件"""
    try:
        file_path = settings.SEAFILE_BODY_DIR + 'body.json'
        return seafile_write_json_direct(file_path, body_data)
        
    except Exception as e:
        logger.error(f"保存身体JSON失败: {e}")
        return False

@csrf_exempt
def upload_clothes(request):
    """新的衣物上传功能，基于云端存储和Coze智能体分类"""
    if request.method == 'POST':
        image_file = request.FILES.get('image')
        if not image_file:
            return JsonResponse({'success': False, 'error': '未上传图片'})
        
        logger.info(f"接收到图片文件: {image_file.name}, 大小: {image_file.size} bytes")
        
        try:
            # 1. 保存图片到本地临时目录
            temp_filename = f"temp_{int(time.time())}.jpg"
            temp_path = os.path.join(settings.TEMP_DIR, temp_filename)
            
            with open(temp_path, 'wb') as f:
                for chunk in image_file.chunks():
                    f.write(chunk)
            
            # 2. 上传到Seafile的TEMP目录
            if not safe_seafile_upload_file(temp_path, settings.SEAFILE_TEMP_DIR):
                return JsonResponse({'success': False, 'error': '上传到临时目录失败'})
            
            # 3. 获取图片的下载链接
            temp_file_path = settings.SEAFILE_TEMP_DIR + temp_filename
            image_url = safe_seafile_download_url(temp_file_path)
            if not image_url:
                return JsonResponse({'success': False, 'error': '获取图片链接失败'})
            
            # 4. 调用Coze平台进行分类
            classify_result = call_coze_classify(image_url)
            if not classify_result:
                logger.error("Coze分类返回空结果")
                return JsonResponse({
                    'success': False, 
                    'error': '分类失败：服务器暂时繁忙，请稍后重试。如果问题持续存在，请联系管理员。'
                })
            
            # 5. 解析分类结果
            clothing_type, features = parse_classify_result(classify_result)
            logger.info(f"分类结果解析完成: 类型={clothing_type}, 特征={features}")
            
            # 验证分类结果
            if not clothing_type or clothing_type == 'unknown':
                logger.error("分类结果无效")
                return JsonResponse({'success': False, 'error': '分类失败：无法识别衣物类型'})
            
            # 6. 处理图片（抠图、加白底、裁剪）
            original_image = seafile_access_image(temp_file_path)
            if original_image:
                # 抠图
                no_bg = remove_background(original_image)
                # 加白底
                with_white = add_white_background(no_bg)
                # 裁剪
                cropped = crop_non_white_content(with_white)
                
                # 保存处理后的图片
                processed_filename = get_simple_filename(clothing_type)
                processed_path = os.path.join(settings.TEMP_DIR, processed_filename)
                cropped.save(processed_path)
                
                # 上传到MyCloset目录
                logger.info(f"开始上传处理后的图片: {processed_filename}")
                if safe_seafile_upload_file(processed_path, settings.SEAFILE_CLOSET_DIR):
                    logger.info("图片上传成功，开始更新JSON文件")
                    
                    # 更新closet.json
                    closet_data = load_closet_json()
                    closet_data[processed_filename] = {
                        'type': clothing_type,
                        'features': features,
                        'upload_time': time.time()
                    }
                    
                    if save_closet_json(closet_data):
                        logger.info("JSON文件更新成功")
                        
                        # 清理临时文件
                        if os.path.exists(temp_path):
                            os.remove(temp_path)
                        if os.path.exists(processed_path):
                            os.remove(processed_path)
                        
                        # 自动生成搭配推荐
                        try:
                            auto_generate_outfit_after_upload(processed_filename)
                        except Exception as e:
                            logger.warning(f"自动生成搭配推荐失败: {e}")
                        
                        # 映射分类到closet页面分类
                        closet_category = map_classification_to_category(clothing_type)
                        
                        return JsonResponse({
                            'success': True, 
                            'label': clothing_type,
                            'features': features,
                            'filename': processed_filename,
                            'closet_category': closet_category,
                            'message': '衣物上传并分类成功'
                        })
                    else:
                        logger.error("JSON文件更新失败")
                        return JsonResponse({'success': False, 'error': '保存衣物信息失败'})
                else:
                    logger.error("图片上传到衣柜失败")
                    return JsonResponse({'success': False, 'error': '上传到衣柜失败'})
            else:
                logger.error("图片处理失败")
                return JsonResponse({'success': False, 'error': '图片处理失败'})
                
        except Exception as e:
            logger.error(f"分类过程出错: {e}")
            return JsonResponse({'success': False, 'error': f'分类过程出错: {str(e)}'})
    
    return JsonResponse({'success': False, 'error': '只支持 POST'})


def call_coze_matching_recommendation(weather_info_str, closet_json_str):
    """
    调用Coze智能体获取搭配推荐
    """
    try:
        print(f"=== 开始调用Coze智能体获取搭配推荐 ===")
        print(f"天气信息: {weather_info_str}")
        print(f"衣柜信息: {closet_json_str[:200]}...")
        
        coze = Coze(auth=TokenAuth(token=settings.COZE_TOKEN), base_url=settings.COZE_API_BASE)
        
        stream = coze.workflows.runs.stream(
            workflow_id=settings.COZE_MATCHING_WORKFLOW_ID,
            parameters={
                "file_link": closet_json_str,   # 衣柜信息作为file_link参数
                "weather": weather_info_str     # 天气信息作为weather参数
            }
        )
        
        print(f"=== 等待Coze响应 ===")
        for event in stream:
            print(f"=== 接收到事件类型: {event.event} ===")
            
            if event.event == WorkflowEventType.MESSAGE:
                print(f"=== 接收到消息: {event.message} ===")
                # 解析响应，提取output字段
                try:
                    if event.message and hasattr(event.message, 'content') and event.message.content:
                        content = event.message.content
                    else:
                        content = str(event.message) if event.message else "无消息内容"
                    
                    print(f"=== 消息内容: {content} ===")
                    
                    # 尝试解析JSON格式的响应
                    if 'output' in content:
                        # 提取output字段的值
                        import re
                        output_match = re.search(r'"output":\s*"([^"]+)"', content)
                        if output_match:
                            output_value = output_match.group(1)
                            print(f"=== 提取到的output值: {output_value} ===")
                            return output_value
                    
                    # 如果没有找到output字段，返回整个内容
                    return content
                    
                except Exception as e:
                    print(f"=== 解析响应失败: {str(e)} ===")
                    return None
                    
            elif event.event == WorkflowEventType.ERROR:
                print(f"=== Coze返回错误: {event.error} ===")
                return None
        
        print(f"=== 未接收到有效响应 ===")
        return None
        
    except Exception as e:
        print(f"=== 调用Coze智能体失败: {str(e)} ===")
        return None

def get_matching_images(request):
    city = request.GET.get('city')
    weather_info_str = request.GET.get('weather_info', '')
    
    if not city or not weather_info_str:
        return JsonResponse({'error': '缺少必要参数'}, status=400)

    try:
        import json
        import os
        from django.conf import settings
        
        # 解析天气信息
        weather_info = json.loads(weather_info_str)
        condition = weather_info.get('condition', '')
        temp_high = int(weather_info.get('temp_high', 0))
        temp_low = int(weather_info.get('temp_low', 0))
        
        print(f"=== 天气信息解析 ===")
        print(f"天气状况: {condition}")
        print(f"最高温度: {temp_high}")
        print(f"最低温度: {temp_low}")
        
        # 基于天气信息选择推荐目录
        recoms_dir = os.path.join(settings.BASE_DIR, 'static', 'recoms')
        selected_directories = []
        
        # 根据天气条件选择推荐目录
        # 优先基于温度判断，然后考虑阴晴状况
        
        # 如果温度较低，优先选择外套
        if temp_low < 15:
            coat_dirs = [d for d in os.listdir(recoms_dir) if d.startswith('COAT-')]
            # 将外套类添加到前面
            selected_directories = coat_dirs[:2]
            print(f"=== 低温，优先选择外套: {selected_directories} ===")
        # 如果温度较高，优先选择短裤类
        elif temp_low >= 20:
            # 优先选择短裤类
            short_dirs = [d for d in os.listdir(recoms_dir) if d.startswith('SHORTS-')]
            selected_directories.extend(short_dirs[:2])  # 最多取2个
            print(f"=== 高温，选择短裤类: {selected_directories} ===")
        # 如果温度适中，根据阴晴状况选择
        else:
            if condition in ['阴', '多云', '小雨', '中雨', '大雨', '雷阵雨']:
                # 阴天或雨天，优先选择长裤和卫衣
                trouser_dirs = [d for d in os.listdir(recoms_dir) if d.startswith('TROUSERS-')]
                sweatshirt_dirs = [d for d in os.listdir(recoms_dir) if d.startswith('SWEATSHIRT-')]
                selected_directories.extend(trouser_dirs[:2])  # 最多取2个长裤
                selected_directories.extend(sweatshirt_dirs[:1])  # 最多取1个卫衣
                print(f"=== 阴天雨天，选择长裤和卫衣: {selected_directories} ===")
            else:
                # 晴天，选择短裤类
                short_dirs = [d for d in os.listdir(recoms_dir) if d.startswith('SHORTS-')]
                selected_directories.extend(short_dirs[:2])  # 最多取2个
                print(f"=== 晴天，选择短裤类: {selected_directories} ===")
        
        # 如果还没有选择到足够的目录，补充T恤类
        if len(selected_directories) < 2:
            tshirt_dirs = [d for d in os.listdir(recoms_dir) if d.startswith('T-SHIRT-')]
            remaining_count = 2 - len(selected_directories)
            selected_directories.extend(tshirt_dirs[:remaining_count])
            print(f"=== 补充T恤类: {selected_directories} ===")
        
        # 确保最多2个目录
        selected_directories = selected_directories[:2]
        
        image_urls = []
        
        # 从每个选中的目录中获取图片
        for directory in selected_directories:
            dir_path = os.path.join(recoms_dir, directory)
            if os.path.exists(dir_path):
                # 优先查找以"FIT"结尾的文件
                fit_files = [f for f in os.listdir(dir_path) if f.upper().endswith('FIT.JPG') or f.upper().endswith('FIT.PNG')]
                
                if fit_files:
                    # 使用FIT文件
                    image_url = f'/static/recoms/{directory}/{fit_files[0]}'
                    image_urls.append(image_url)
                    print(f"=== 找到FIT文件: {image_url} ===")
                else:
                    # 使用其他文件
                    other_files = [f for f in os.listdir(dir_path) if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
                    if other_files:
                        image_url = f'/static/recoms/{directory}/{other_files[0]}'
                        image_urls.append(image_url)
                        print(f"=== 找到其他文件: {image_url} ===")
        
        print(f"=== 最终选择的图片URLs: {image_urls} ===")
        return JsonResponse({'image_urls': image_urls})
            
    except Exception as e:
        print(f"=== 获取搭配图片时出错: {str(e)} ===")
        return JsonResponse({'error': f'获取搭配图片失败: {str(e)}'}, status=500)

#========音视频功能
    # 火山引擎语音字幕API配置
VOLC_CONFIG = {
    "appid": "2604474986",  # 你的AppID
    "token": "Z981ceaOj5reMSBsG-Jwguu5I4TPzdUk",  # 你的Token
    "api_submit_url": "https://openspeech.bytedance.com/api/v1/vc/submit",
    "api_query_url": "https://openspeech.bytedance.com/api/v1/vc/query",
    # 其他配置参数（根据需要添加）
}

@csrf_exempt
def asr_api(request):
    """语音字幕API处理接口"""
    if request.method != 'POST':
        return JsonResponse({'error': '仅支持POST请求'}, status=405)
    
    try:
        # 1. 检查是否有音频文件
        if 'audio' not in request.FILES:
            logger.error("请求中未包含音频文件")
            return JsonResponse({'error': '未获取到音频文件'}, status=400)
        
        audio_file = request.FILES['audio']
        if not audio_file or audio_file.size == 0:
            logger.error("音频文件为空")
            return JsonResponse({'error': '音频文件为空'}, status=400)
        
        # 2. 提交任务到火山引擎语音字幕API
        task_id = submit_caption_task(audio_file)
        if not task_id:
            return JsonResponse({'error': '提交任务失败'}, status=500)
        
        # 3. 查询结果（使用阻塞模式，无需轮询）
        result = query_caption_result(task_id)
        if not result:
            return JsonResponse({'error': '查询结果失败'}, status=500)
        
        # 4. 处理并返回结果
        return JsonResponse({
            'text': result.get('text', ''),
            'utterances': result.get('utterances', [])
        })
    
    except Exception as e:
        logger.error(f"接口处理异常: {str(e)}", exc_info=True)
        return JsonResponse({'error': f"服务器内部错误: {str(e)}"}, status=500)

def submit_caption_task(audio_file):
    """提交任务到火山引擎语音字幕API"""
    try:
        # 构建URL参数
        params = {
            "appid": VOLC_CONFIG["appid"],
            "language": "zh-CN",
            "use_itn": "true",
            "use_punc": "true",
            "caption_type": "speech",
            "words_per_line": 15,
        }
        
        # 读取音频文件内容
        audio_content = audio_file.read()
        
        # 添加Authorization头（严格按照火山引擎文档格式）
        headers = {
            "Content-Type": "audio/wav",
            "Connection": "keep-alive",
            "Authorization": f"Bearer; {VOLC_CONFIG['token']}"  # 注意格式：Bearer; 空格 Token
        }
        
        logger.debug(f"提交任务请求参数: {params}")
        logger.debug(f"提交任务请求头: {headers}")
        
        # 发送请求
        response = requests.post(
            url=VOLC_CONFIG["api_submit_url"],
            params=params,
            headers=headers,
            data=audio_content,
            timeout=30  # 增加超时时间，避免音频大时超时
        )
        
        # 记录详细的响应信息
        logger.debug(f"提交任务响应状态码: {response.status_code}")
        logger.debug(f"提交任务响应内容: {response.text}")
        
        # 检查响应
        if response.status_code != 200:
            logger.error(f"火山引擎API返回错误: {response.status_code}, {response.text}")
            return None
            
        response_data = response.json()
        
        # 检查是否成功
        if response_data.get("code") == 0 and "id" in response_data:
            logger.info(f"任务提交成功，ID: {response_data['id']}")
            return response_data["id"]
        else:
            logger.error(f"提交任务失败: {response_data.get('message', '未知错误')}")
            return None
    
    except Exception as e:
        logger.error(f"提交任务异常: {str(e)}", exc_info=True)
        return None

def query_caption_result(task_id):
    """查询字幕结果（使用阻塞模式）"""
    try:
        # 构建查询参数
        params = {
            "appid": VOLC_CONFIG["appid"],
            "id": task_id,
            "blocking": 1  # 阻塞模式，等待结果
        }
        
        # 添加Authorization头（关键修复点）
        headers = {
            "Authorization": f"Bearer; {VOLC_CONFIG['token']}"  # 必须包含Token
        }
        
        logger.debug(f"查询结果请求参数: {params}")
        
        # 发送GET请求查询结果（使用阻塞模式，一次请求即可）
        response = requests.get(
            url=VOLC_CONFIG["api_query_url"],
            params=params,
            headers=headers,  # 添加Authorization头
            timeout=60  # 增加超时时间，处理长音频
        )
        
        # 记录响应信息
        logger.debug(f"查询结果响应状态码: {response.status_code}")
        logger.debug(f"查询结果响应内容: {response.text}")
        
        if response.status_code != 200:
            logger.error(f"查询结果HTTP错误: {response.status_code}, {response.text}")
            return None
            
        response_data = response.json()
        
        # 检查状态
        if response_data.get("code") == 0:
            # 成功获取结果
            result = {
                "text": "",
                "utterances": []
            }
            
            # 根据文档解析响应数据
            if "utterances" in response_data:
                result["utterances"] = response_data["utterances"]
                # 合并所有utterances的文本
                result["text"] = "".join([u.get("text", "") for u in response_data["utterances"]])
            
            return result
        else:
            # 其他错误
            logger.error(f"查询失败: {response_data.get('message', '未知错误')}")
            return None
    
    except Exception as e:
        logger.error(f"查询结果异常: {str(e)}", exc_info=True)
        return None

# ========== HTTPS开发环境支持 ==========

class HTTPSRedirectMiddleware:
    """开发环境HTTPS重定向中间件"""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # 检查是否在开发环境且不是HTTPS
        if (settings.DEBUG and 
            request.get_host() not in ['localhost', '127.0.0.1'] and
            not request.is_secure()):
            # 重定向到HTTPS
            from django.http import HttpResponseRedirect
            secure_url = request.build_absolute_uri().replace('http://', 'https://')
            return HttpResponseRedirect(secure_url)
        
        return self.get_response(request)

# ========== 衣物搭配推荐功能 ==========

# 衣物分类映射（用于拼图时的上下位置判断）
UPPER_GARMENTS = {"T-SHIRT", "COAT", "CARDIGAN", "SHIRT", "SUIT", "SWEATSHIRT"}
LOWER_GARMENTS = {"SHORTS", "SHORT-SKIRT", "TROUSERS"}
DRESS_GARMENTS = {"DRESS"}

def is_upper_garment(clothing_type):
    """判断是否为上衣"""
    return clothing_type.upper() in UPPER_GARMENTS

def is_lower_garment(clothing_type):
    """判断是否为下装"""
    return clothing_type.upper() in LOWER_GARMENTS

def is_dress_garment(clothing_type):
    """判断是否为连衣裙"""
    return clothing_type.upper() in DRESS_GARMENTS

def get_garment_position(clothing_type):
    """获取衣物在拼图中的位置（上/下）"""
    if is_upper_garment(clothing_type):
        return "upper"
    elif is_lower_garment(clothing_type):
        return "lower"
    elif is_dress_garment(clothing_type):
        return "dress"
    else:
        return "unknown"

def call_coze_outfit_recommendation(img_link, closet_json_str):
    """调用Coze智能体获取搭配推荐"""
    try:
        logger.info("=== 开始调用Coze搭配推荐 ===")
        logger.info(f"图片链接: {img_link}")
        logger.info(f"衣柜JSON长度: {len(closet_json_str)}")
        
        # 使用与coze3.py相同的配置
        coze = Coze(
            auth=TokenAuth(token=settings.COZE_TOKEN), 
            base_url=settings.COZE_API_BASE
        )
        
        # 使用搭配推荐的workflow_id
        workflow_id = '7527252966903726120'  # 从coze3.py获取的workflow_id
        
        stream = coze.workflows.runs.stream(
            workflow_id=workflow_id,
            parameters={
                "img_link": img_link,
                "file": closet_json_str
            }
        )
        
        for event in stream:
            if event.event == WorkflowEventType.MESSAGE:
                print(f"=== Coze搭配推荐原始输出 ===")
                print(f"输出内容: {event.message}")
                print(f"输出类型: {type(event.message)}")
                print(f"输出长度: {len(str(event.message))}")
                logger.info(f"搭配推荐结果: {event.message}")
                return str(event.message)
            elif event.event == WorkflowEventType.ERROR:
                print(f"=== Coze搭配推荐错误 ===")
                print(f"错误内容: {event.error}")
                logger.error(f"搭配推荐错误: {event.error}")
                return None
                
    except Exception as e:
        logger.error(f"调用Coze搭配推荐失败: {e}")
        return None

def parse_outfit_recommendation(result_str, original_garment=None):
    """解析搭配推荐结果"""
    try:
        print(f"=== 开始解析搭配推荐结果 ===")
        print(f"输入类型: {type(result_str)}")
        print(f"输入内容: {result_str}")
        print(f"输入内容repr: {repr(result_str)}")
        print(f"原衣物文件名: {original_garment}")
        logger.info(f"解析搭配推荐结果: {result_str}")
        
        # 直接提取"output"字段后面的内容
        print(f"=== 直接提取output字段内容 ===")
        
        # 查找"output":后面的内容
        import re
        output_pattern = r'"output":\s*"([^"]*)"'
        output_match = re.search(output_pattern, result_str)
        
        if output_match:
            output = output_match.group(1)
            print(f"找到output字段内容: {output}")
            logger.info(f"提取的output字段内容: {output}")
        else:
            print(f"=== 未找到output字段，尝试其他方法 ===")
            # 如果没有找到标准的"output"字段，尝试其他方法
            try:
                # 尝试JSON解析
                result_data = json.loads(result_str)
                output = result_data.get('output', '')
                print(f"JSON解析成功，提取output: {output}")
            except json.JSONDecodeError:
                # 如果JSON解析失败，直接使用原始字符串
                output = result_str
                print(f"JSON解析失败，使用原始字符串: {output}")
        
        print(f"=== 最终使用的output ===")
        print(f"output内容: {output}")
        print(f"output长度: {len(output)}")
        print(f"output类型: {type(output)}")
        logger.info(f"提取的output: {output}")
        
        # 检查是否为非法输出
        illegal_outputs = ['', 'null', 'None', '无搭配', '没有找到搭配', '无法生成搭配', '无', '没有', '无法', '请', '明确']
        if not output or output.strip() in illegal_outputs:
            print(f"=== 检测到非法输出 ===")
            print(f"output.strip(): {output.strip()}")
            logger.warning("Coze返回非法输出，无有效搭配信息")
            return []
        
        print(f"=== 开始解析搭配信息 ===")
        # 解析搭配信息，支持多种格式
        outfits = []
        
        # 预处理：处理换行符和特殊字符
        output = output.replace('\\n', '\n').replace('\\t', '\t')
        print(f"预处理后的output: {output}")
        
        # 处理带编号前缀的格式，如 "1.T-SHIRT-002；2.SWEATSHIRT-002"
        # 将 "数字.内容；数字.内容" 的格式转换为标准格式
        import re
        # 匹配 "数字.内容" 的模式
        numbered_pattern = r'(\d+)\.([^；]+)'
        matches = re.findall(numbered_pattern, output)
        if matches:
            print(f"检测到带编号前缀的格式: {matches}")
            # 提取所有编号后面的内容
            extracted_parts = []
            for number, content in matches:
                extracted_parts.append(content.strip())
            # 重新组合为分号分隔的格式
            output = '；'.join(extracted_parts)
            print(f"转换后的格式: {output}")
        
        # 获取原衣物的基础名称（去掉扩展名）
        original_base = None
        if original_garment:
            original_base = os.path.splitext(original_garment)[0]
            print(f"原衣物基础名称: {original_base}")
        
        # 首先尝试按换行符分割多个搭配
        if '\n' in output:
            print(f"=== 检测到多个搭配（换行符分隔） ===")
            parts = output.split('\n')
            print(f"分割后的部分: {parts}")
            
            for i, part in enumerate(parts):
                part = part.strip()
                if not part:
                    continue
                print(f"=== 处理第 {i+1} 个部分: {part} ===")
                garment_name = extract_garment_name(part)
                if garment_name:
                    # 检查是否与原衣物相同
                    if original_base and garment_name == original_base:
                        print(f"=== 跳过与原衣物相同的搭配: {garment_name} ===")
                        continue
                    print(f"=== 提取到搭配衣物: {garment_name} ===")
                    outfits.append(garment_name)
                else:
                    print(f"=== 无法提取搭配衣物，跳过: {part} ===")
        
        # 如果没有换行符，尝试按分号分割多个搭配
        elif ';' in output or '；' in output:
            print(f"=== 检测到多个搭配（分号分隔） ===")
            # 同时处理英文分号和中文分号
            if '；' in output:
                parts = output.split('；')
                print(f"使用中文分号分割")
            else:
                parts = output.split(';')
                print(f"使用英文分号分割")
            print(f"分割后的部分: {parts}")
            
            for i, part in enumerate(parts):
                part = part.strip()
                if not part:
                    continue
                print(f"=== 处理第 {i+1} 个部分: {part} ===")
                garment_name = extract_garment_name(part)
                if garment_name:
                    # 检查是否与原衣物相同
                    if original_base and garment_name == original_base:
                        print(f"=== 跳过与原衣物相同的搭配: {garment_name} ===")
                        continue
                    print(f"=== 提取到搭配衣物: {garment_name} ===")
                    outfits.append(garment_name)
                else:
                    print(f"=== 无法提取搭配衣物，跳过: {part} ===")
        
        # 如果没有分号，尝试按冒号分割单个搭配
        elif '：' in output:
            print(f"=== 检测到单个搭配（冒号分隔） ===")
            garment_name = extract_garment_name(output)
            if garment_name:
                # 检查是否与原衣物相同
                if original_base and garment_name == original_base:
                    print(f"=== 跳过与原衣物相同的搭配: {garment_name} ===")
                    return []
                print(f"=== 提取到搭配衣物: {garment_name} ===")
                outfits.append(garment_name)
            else:
                print(f"=== 无法提取搭配衣物: {output} ===")
        
        # 如果都没有，尝试直接解析
        else:
            print(f"=== 尝试直接解析整个字符串 ===")
            garment_name = extract_garment_name(output)
            if garment_name:
                # 检查是否与原衣物相同
                if original_base and garment_name == original_base:
                    print(f"=== 跳过与原衣物相同的搭配: {garment_name} ===")
                    return []
                print(f"=== 提取到搭配衣物: {garment_name} ===")
                outfits.append(garment_name)
            else:
                print(f"=== 无法提取搭配衣物: {output} ===")
        
        print(f"=== 解析完成 ===")
        print(f"最终搭配列表: {outfits}")
        logger.info(f"解析出的搭配: {outfits}")
        
        # 如果没有解析到有效搭配，返回空列表
        if not outfits:
            print(f"=== 未解析到有效搭配 ===")
            logger.warning("未解析到有效的搭配信息")
            return []
        
        print(f"=== 解析成功，返回 {len(outfits)} 个搭配 ===")
        return outfits
        
    except Exception as e:
        print(f"=== 解析过程出现异常 ===")
        print(f"异常类型: {type(e)}")
        print(f"异常内容: {e}")
        logger.error(f"解析搭配推荐失败: {e}")
        return []

def extract_garment_name(text):
    """从文本中提取衣物名称"""
    try:
        print(f"=== 提取衣物名称 ===")
        print(f"输入文本: {text}")
        
        # 如果包含冒号，取冒号后面的部分
        if '：' in text:
            parts = text.split('：', 1)
            garment_name = parts[1].strip()
            print(f"冒号分割后: {garment_name}")
        else:
            garment_name = text.strip()
            print(f"直接使用文本: {garment_name}")
        
        # 检查衣物名称是否有效
        if not garment_name or garment_name in ['', 'null', 'None']:
            print(f"衣物名称无效: {garment_name}")
            return None
        
        # 预处理：移除多余的空格和特殊字符
        import re
        garment_name = re.sub(r'\s+', ' ', garment_name)  # 将多个空格替换为单个空格
        garment_name = garment_name.strip()
        print(f"预处理后: {garment_name}")
        
        # 处理带编号前缀的格式，如 "1.T-SHIRT-002"
        if '.' in garment_name and re.match(r'^\d+\.', garment_name):
            # 提取点号后面的部分
            parts = garment_name.split('.', 1)
            if len(parts) == 2:
                garment_name = parts[1].strip()  # 取点号后面的部分
                print(f"移除编号前缀后: {garment_name}")
        
        # 清理文件名，只保留大写部分
        print(f"=== 开始清理文件名: {garment_name} ===")
        cleaned_name = clean_garment_filename(garment_name)
        
        if cleaned_name:
            print(f"=== 清理成功: {cleaned_name} ===")
            return cleaned_name
        else:
            print(f"=== 清理失败: {garment_name} ===")
            return None
            
    except Exception as e:
        print(f"提取衣物名称失败: {e}")
        return None

def clean_garment_filename(filename):
    """清理衣物文件名，只保留大写部分"""
    try:
        print(f"=== 开始清理文件名 ===")
        print(f"输入文件名: {filename}")
        print(f"输入类型: {type(filename)}")
        logger.info(f"清理文件名: {filename}")
        
        # 保存原始文件名用于日志输出
        original_filename = filename
        
        # 预处理：移除空格和特殊字符，但保留字母、数字、连字符和点号
        import re
        # 首先移除多余的空格
        filename = re.sub(r'\s+', '', filename)
        # 移除除了字母、数字、连字符、点号之外的特殊字符
        filename = re.sub(r'[^\w\-\.]', '', filename)
        print(f"预处理后: {filename}")
        
        # 处理带编号前缀的格式，如 "1.T-SHIRT-002"
        if '.' in filename and re.match(r'^\d+\.', filename):
            # 提取点号后面的部分
            parts = filename.split('.', 1)
            if len(parts) == 2:
                filename = parts[1]  # 取点号后面的部分
                print(f"移除编号前缀后: {filename}")
        
        print(f"=== 开始查找大写字母序列 ===")
        # 查找大写字母部分（通常是衣物类型）
        
        # 定义有效的衣物类型（避免提取单个字母）
        valid_garment_types = {
            'TROUSERS', 'SHIRT', 'DRESS', 'COAT', 'CARDIGAN', 'SUIT', 
            'SWEATSHIRT', 'SHORTS', 'SKIRT', 'T-SHIRT', 'TSHIRT'
        }
        
        print(f"=== 尝试匹配带连字符的衣物类型 ===")
        # 首先尝试匹配带连字符的衣物类型，如 T-SHIRT
        hyphenated_matches = re.findall(r'[A-Z]+-[A-Z]+', filename)
        print(f"带连字符的匹配: {hyphenated_matches}")
        
        if hyphenated_matches:
            # 如果找到带连字符的匹配，优先使用
            main_type = max(hyphenated_matches, key=len)
            print(f"选择带连字符的类型: {main_type}")
            logger.info(f"提取的带连字符类型: {main_type}")
        else:
            print(f"=== 未找到带连字符的匹配，尝试普通大写字母序列 ===")
            # 匹配大写字母序列，如 TROUSERS, SHIRT 等
            uppercase_matches = re.findall(r'[A-Z]+', filename)
            print(f"找到的大写字母序列: {uppercase_matches}")
            
            # 过滤出有效的衣物类型
            valid_matches = []
            for match in uppercase_matches:
                if match in valid_garment_types:
                    valid_matches.append(match)
                elif len(match) >= 3:  # 如果长度>=3且不在预定义列表中，也认为是有效的
                    valid_matches.append(match)
            
            print(f"有效的衣物类型匹配: {valid_matches}")
            
            if valid_matches:
                # 取最长的大写字母序列
                main_type = max(valid_matches, key=len)
                print(f"选择的主要类型: {main_type}")
                logger.info(f"提取的大写类型: {main_type}")
            else:
                print(f"=== 未找到有效的大写字母序列 ===")
                main_type = None
        
        if main_type:
            print(f"=== 开始查找数字部分 ===")
            # 查找数字部分（通常是编号）
            number_match = re.search(r'\d+', filename)
            if number_match:
                number = number_match.group()
                print(f"找到的数字: {number}")
                cleaned_name = f"{main_type}-{number.zfill(3)}"
            else:
                # 如果没有数字，使用默认编号
                print(f"未找到数字，使用默认编号: 001")
                cleaned_name = f"{main_type}-001"
            
            print(f"=== 清理完成 ===")
            print(f"原始文件名: {original_filename}")
            print(f"清理后文件名: {cleaned_name}")
            logger.info(f"清理后的文件名: {cleaned_name}")
            return cleaned_name
        else:
            print(f"=== 未找到大写字母序列 ===")
            print(f"文件名: {filename}")
            print(f"尝试其他匹配方式...")
            
            # 尝试匹配小写字母+数字的组合
            # 首先尝试匹配带连字符的小写格式，如 t-shirt
            lowercase_hyphenated = re.findall(r'[a-z]+-[a-z]+', filename)
            print(f"找到的带连字符小写序列: {lowercase_hyphenated}")
            
            if lowercase_hyphenated:
                # 如果找到带连字符的小写格式，优先使用
                main_type = max(lowercase_hyphenated, key=len).upper()
                print(f"转换后的带连字符类型: {main_type}")
                
                # 查找数字部分
                number_match = re.search(r'\d+', filename)
                if number_match:
                    number = number_match.group()
                    print(f"找到的数字: {number}")
                    cleaned_name = f"{main_type}-{number.zfill(3)}"
                else:
                    print(f"未找到数字，使用默认编号: 001")
                    cleaned_name = f"{main_type}-001"
                
                print(f"=== 清理完成（小写连字符转换） ===")
                print(f"原始文件名: {original_filename}")
                print(f"清理后文件名: {cleaned_name}")
                logger.info(f"清理后的文件名（小写连字符转换）: {cleaned_name}")
                return cleaned_name
            else:
                # 如果没有带连字符的格式，尝试普通小写字母序列
                lowercase_matches = re.findall(r'[a-z]+', filename)
                print(f"找到的小写字母序列: {lowercase_matches}")
                
                # 过滤出有效的小写字母序列（长度>=3）
                valid_lowercase_matches = [match for match in lowercase_matches if len(match) >= 3]
                print(f"有效的小写字母序列: {valid_lowercase_matches}")
                
                if valid_lowercase_matches:
                    # 取最长的小写字母序列并转为大写
                    main_type = max(valid_lowercase_matches, key=len).upper()
                    print(f"转换后的类型: {main_type}")
                else:
                    print(f"=== 未找到有效的小写字母序列 ===")
                    logger.warning(f"未找到大写字母序列: {filename}")
                    return None
                
                # 查找数字部分
                number_match = re.search(r'\d+', filename)
                if number_match:
                    number = number_match.group()
                    print(f"找到的数字: {number}")
                    cleaned_name = f"{main_type}-{number.zfill(3)}"
                else:
                    print(f"未找到数字，使用默认编号: 001")
                    cleaned_name = f"{main_type}-001"
                
                print(f"=== 清理完成（小写转换） ===")
                print(f"原始文件名: {original_filename}")
                print(f"清理后文件名: {cleaned_name}")
                logger.info(f"清理后的文件名（小写转换）: {cleaned_name}")
                return cleaned_name
            
    except Exception as e:
        print(f"=== 清理文件名过程出现异常 ===")
        print(f"异常类型: {type(e)}")
        print(f"异常内容: {e}")
        logger.error(f"清理文件名失败: {e}")
        return None

def create_outfit_image(main_garment_path, outfit_garment_path, output_filename, subdirectory=None):
    """创建搭配图片"""
    try:
        print(f"=== 开始创建搭配图片 ===")
        print(f"输出文件名: {output_filename}")
        print(f"子目录: {subdirectory}")
        print(f"主衣物路径: {main_garment_path}")
        print(f"搭配衣物路径: {outfit_garment_path}")
        logger.info(f"开始创建搭配图片: {output_filename}")
        
        # 获取主衣物图片
        print(f"=== 获取主衣物图片 ===")
        print(f"主衣物路径: {main_garment_path}")
        main_image = seafile_access_image(main_garment_path)
        if not main_image:
            print(f"=== 无法获取主衣物图片 ===")
            logger.error(f"无法获取主衣物图片: {main_garment_path}")
            return False
        else:
            print(f"=== 主衣物图片获取成功 ===")
            print(f"主衣物图片类型: {type(main_image)}")
            print(f"主衣物图片尺寸: {main_image.size if hasattr(main_image, 'size') else '未知'}")
        
        # 获取搭配衣物图片
        print(f"=== 获取搭配衣物图片 ===")
        print(f"搭配衣物路径: {outfit_garment_path}")
        outfit_image = seafile_access_image(outfit_garment_path)
        if not outfit_image:
            print(f"=== 无法获取搭配衣物图片 ===")
            logger.error(f"无法获取搭配衣物图片: {outfit_garment_path}")
            return False
        else:
            print(f"=== 搭配衣物图片获取成功 ===")
            print(f"搭配衣物图片类型: {type(outfit_image)}")
            print(f"搭配衣物图片尺寸: {outfit_image.size if hasattr(outfit_image, 'size') else '未知'}")
        
        # 处理图片（抠图、加白底、裁剪）
        print(f"=== 开始处理主衣物图片 ===")
        main_processed = crop_non_white_content(add_white_background(remove_background(main_image)))
        print(f"=== 主衣物图片处理完成 ===")
        
        print(f"=== 开始处理搭配衣物图片 ===")
        outfit_processed = crop_non_white_content(add_white_background(remove_background(outfit_image)))
        print(f"=== 搭配衣物图片处理完成 ===")
        
        # 获取衣物类型信息
        print(f"=== 获取衣物类型信息 ===")
        main_garment_type = get_garment_type_from_path(main_garment_path)
        outfit_garment_type = get_garment_type_from_path(outfit_garment_path)
        print(f"主衣物类型: {main_garment_type}")
        print(f"搭配衣物类型: {outfit_garment_type}")
        
        # 检查搭配组合是否合理
        print(f"=== 检查搭配合理性 ===")
        is_valid = is_valid_outfit_combination(main_garment_type, outfit_garment_type)
        print(f"=== 搭配合理性检查结果: {is_valid} ===")
        
        if not is_valid:
            print(f"❌ 搭配组合不合理，跳过创建搭配图片")
            logger.warning(f"搭配组合不合理: {main_garment_type} + {outfit_garment_type}")
            return False
        
        # 根据衣物类型决定拼接顺序
        print(f"=== 决定拼接顺序 ===")
        if should_place_upper_first(main_garment_type, outfit_garment_type):
            print(f"上衣放在上面，下装放在下面")
            upper_image = main_processed
            lower_image = outfit_processed
        else:
            print(f"搭配衣物放在上面，主衣物放在下面")
            upper_image = outfit_processed
            lower_image = main_processed
        
        # 拼接图片
        print(f"=== 开始拼接图片 ===")
        combined_image = concat_images_vertically(upper_image, lower_image)
        print(f"=== 图片拼接完成 ===")
        
        # 保存到本地
        if subdirectory:
            # 如果有子目录，保存到子目录中
            local_path = os.path.join(settings.BASE_DIR, 'static', 'recoms', subdirectory, output_filename)
            print(f"=== 保存搭配图片到子目录 ===")
            print(f"保存路径: {local_path}")
        else:
            # 如果没有子目录，保存到根目录
            local_path = os.path.join(settings.BASE_DIR, 'static', 'recoms', output_filename)
            print(f"=== 保存搭配图片到根目录 ===")
            print(f"保存路径: {local_path}")
        
        combined_image.save(local_path)
        
        print(f"=== 搭配图片创建成功 ===")
        logger.info(f"搭配图片创建成功: {local_path}")
        return True
        
    except Exception as e:
        print(f"=== 创建搭配图片过程出现异常 ===")
        print(f"异常类型: {type(e)}")
        print(f"异常内容: {e}")
        logger.error(f"创建搭配图片失败: {e}")
        return False

def get_garment_type_from_path(garment_path):
    """从衣物路径中提取衣物类型"""
    try:
        # 从路径中提取文件名
        filename = os.path.basename(garment_path)
        print(f"从路径提取文件名: {filename}")
        
        # 去掉扩展名
        name_without_ext = os.path.splitext(filename)[0]
        print(f"去掉扩展名: {name_without_ext}")
        
        # 提取衣物类型（去掉数字部分）
        import re
        # 匹配字母部分，如 T-SHIRT, TROUSERS 等
        type_match = re.match(r'^([A-Z-]+)', name_without_ext)
        if type_match:
            garment_type = type_match.group(1)
            # 去掉末尾的连字符
            garment_type = garment_type.rstrip('-')
            print(f"提取的衣物类型: {garment_type}")
            return garment_type
        else:
            print(f"无法从文件名提取衣物类型: {name_without_ext}")
            return "UNKNOWN"
            
    except Exception as e:
        print(f"提取衣物类型失败: {e}")
        return "UNKNOWN"

def should_place_upper_first(main_type, outfit_type):
    """判断是否应该将上衣放在上面"""
    print(f"=== 判断拼接顺序 ===")
    print(f"主衣物类型: {main_type}")
    print(f"搭配衣物类型: {outfit_type}")
    
    # 判断主衣物是否为上衣
    main_is_upper = is_upper_garment(main_type)
    outfit_is_upper = is_upper_garment(outfit_type)
    main_is_lower = is_lower_garment(main_type)
    outfit_is_lower = is_lower_garment(outfit_type)
    
    print(f"主衣物是上衣: {main_is_upper}")
    print(f"搭配衣物是上衣: {outfit_is_upper}")
    print(f"主衣物是下装: {main_is_lower}")
    print(f"搭配衣物是下装: {outfit_is_lower}")
    
    # 如果主衣物是上衣，搭配衣物是下装，则主衣物在上
    if main_is_upper and outfit_is_lower:
        print(f"主衣物是上衣，搭配衣物是下装，主衣物放在上面")
        return True
    # 如果搭配衣物是上衣，主衣物是下装，则搭配衣物在上
    elif outfit_is_upper and main_is_lower:
        print(f"搭配衣物是上衣，主衣物是下装，搭配衣物放在上面")
        return False
    # 如果都是上衣或都是下装，按默认顺序（主衣物在上）
    else:
        print(f"相同类型或未知类型，按默认顺序（主衣物在上）")
        return True

def is_valid_outfit_combination(main_type, outfit_type):
    """检查搭配组合是否合理"""
    print(f"=== 检查搭配合理性 ===")
    print(f"主衣物类型: {main_type}")
    print(f"搭配衣物类型: {outfit_type}")
    
    # 如果两个都是同类型，则不合理
    if main_type == outfit_type:
        print(f"❌ 同类型搭配不合理: {main_type} + {outfit_type}")
        return False
    
    # 如果都是上衣类型，则不合理
    if is_upper_garment(main_type) and is_upper_garment(outfit_type):
        print(f"❌ 两件上衣搭配不合理: {main_type} + {outfit_type}")
        return False
    
    # 如果都是下装类型，则不合理
    if is_lower_garment(main_type) and is_lower_garment(outfit_type):
        print(f"❌ 两件下装搭配不合理: {main_type} + {outfit_type}")
        return False
    
    print(f"✅ 搭配组合合理: {main_type} + {outfit_type}")
    return True

@csrf_exempt
def generate_outfit_recommendations(request):
    """为指定衣物生成搭配推荐"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            garment_filename = data.get('garment_filename')
            
            if not garment_filename:
                return JsonResponse({'success': False, 'error': '缺少衣物文件名'})
            
            logger.info(f"开始为衣物生成搭配推荐: {garment_filename}")
            
            # 1. 获取衣物图片下载链接
            garment_path = settings.SEAFILE_CLOSET_DIR + garment_filename
            img_link = safe_seafile_download_url(garment_path)
            if not img_link:
                return JsonResponse({'success': False, 'error': '无法获取衣物图片链接'})
            
            # 2. 获取衣柜JSON内容
            closet_json_path = settings.SEAFILE_CLOSET_DIR + 'closet.json'
            closet_data = seafile_read_json(closet_json_path)
            if not closet_data:
                return JsonResponse({'success': False, 'error': '无法获取衣柜数据'})
            
            closet_json_str = json.dumps(closet_data, ensure_ascii=False)
            
            # 3. 调用Coze获取搭配推荐
            recommendation_result = call_coze_outfit_recommendation(img_link, closet_json_str)
            if not recommendation_result:
                return JsonResponse({'success': False, 'error': '获取搭配推荐失败'})
            
            # 4. 解析搭配推荐
            outfit_garments = parse_outfit_recommendation(recommendation_result, garment_filename)
            if not outfit_garments:
                return JsonResponse({'success': False, 'error': '解析搭配推荐失败'})
            
            # 5. 创建搭配图片
            base_filename = os.path.splitext(garment_filename)[0]  # 去掉扩展名
            recoms_dir = os.path.join(settings.BASE_DIR, 'static', 'recoms', base_filename)
            
            # 确保目录存在
            if not os.path.exists(recoms_dir):
                os.makedirs(recoms_dir)
            
            created_outfits = []
            print(f"=== 开始处理搭配列表 ===")
            print(f"搭配衣物列表: {outfit_garments}")
            print(f"搭配衣物数量: {len(outfit_garments)}")
            
            for i, outfit_garment in enumerate(outfit_garments[:2]):  # 最多处理2套搭配
                print(f"=== 处理第 {i+1} 套搭配 ===")
                print(f"搭配衣物名称: {outfit_garment}")
                
                # 构造搭配衣物文件名
                outfit_filename = f"{outfit_garment}.jpg"
                outfit_path = settings.SEAFILE_CLOSET_DIR + outfit_filename
                print(f"构造的文件路径: {outfit_path}")
                print(f"正在请求图片: {outfit_filename}")
                
                # 创建搭配图片
                coord_filename = f"{base_filename}-COORD{i+1}.jpg"
                coord_path = os.path.join(recoms_dir, coord_filename)
                print(f"搭配图片文件名: {coord_filename}")
                
                print(f"=== 开始创建搭配图片 ===")
                print(f"主衣物路径: {garment_path}")
                print(f"搭配衣物路径: {outfit_path}")
                print(f"输出文件名: {coord_filename}")
                print(f"子目录: {base_filename}")
                
                try:
                    result = create_outfit_image(garment_path, outfit_path, coord_filename, base_filename)
                    print(f"=== create_outfit_image 返回结果: {result} ===")
                    
                    if result:
                        print(f"=== 搭配图片创建成功 ===")
                        created_outfits.append({
                            'coord_filename': coord_filename,
                            'coord_path': f'/static/recoms/{base_filename}/{coord_filename}'
                        })
                    else:
                        print(f"=== 搭配图片创建失败 ===")
                except Exception as e:
                    print(f"=== 创建搭配图片时出现异常 ===")
                    print(f"异常类型: {type(e)}")
                    print(f"异常内容: {e}")
                    logger.error(f"创建搭配图片异常: {e}")
            
            print(f"=== 搭配处理完成 ===")
            print(f"成功创建的搭配数量: {len(created_outfits)}")
            print(f"创建的搭配列表: {created_outfits}")
            
            if created_outfits:
                return JsonResponse({
                    'success': True,
                    'outfits': created_outfits,
                    'message': f'成功生成 {len(created_outfits)} 套搭配推荐'
                })
            else:
                return JsonResponse({'success': False, 'error': '搭配图片生成失败'})
                
        except Exception as e:
            logger.error(f"生成搭配推荐失败: {e}")
            return JsonResponse({'success': False, 'error': f'生成搭配推荐失败: {str(e)}'})
    
    return JsonResponse({'success': False, 'error': '只支持POST请求'})

def auto_generate_outfit_after_upload(garment_filename):
    """上传衣物后自动生成搭配推荐"""
    try:
        logger.info(f"自动为上传的衣物生成搭配推荐: {garment_filename}")
        
        # 延迟一段时间确保文件已上传完成
        import time
        time.sleep(2)
        
        # 调用搭配推荐生成函数
        garment_path = settings.SEAFILE_CLOSET_DIR + garment_filename
        img_link = safe_seafile_download_url(garment_path)
        if not img_link:
            logger.warning(f"无法获取衣物图片链接: {garment_filename}")
            return False
        
        # 获取衣柜JSON内容
        closet_json_path = settings.SEAFILE_CLOSET_DIR + 'closet.json'
        closet_data = seafile_read_json(closet_json_path)
        if not closet_data:
            logger.warning("无法获取衣柜数据")
            return False
        
        closet_json_str = json.dumps(closet_data, ensure_ascii=False)
        
        # 调用Coze获取搭配推荐
        recommendation_result = call_coze_outfit_recommendation(img_link, closet_json_str)
        if not recommendation_result:
            logger.warning(f"获取搭配推荐失败: {garment_filename}")
            return False
        
        # 解析搭配推荐
        outfit_garments = parse_outfit_recommendation(recommendation_result, garment_filename)
        if not outfit_garments:
            logger.warning(f"解析搭配推荐失败或无有效搭配: {garment_filename}")
            return False
        
        # 创建搭配图片
        base_filename = os.path.splitext(garment_filename)[0]
        recoms_dir = os.path.join(settings.BASE_DIR, 'static', 'recoms', base_filename)
        
        # 确保目录存在
        if not os.path.exists(recoms_dir):
            os.makedirs(recoms_dir)
        
        success_count = 0
        for i, outfit_garment in enumerate(outfit_garments[:2]):
            outfit_filename = f"{outfit_garment}.jpg"
            outfit_path = settings.SEAFILE_CLOSET_DIR + outfit_filename
            
            coord_filename = f"{base_filename}-COORD{i+1}.jpg"
            coord_path = os.path.join(recoms_dir, coord_filename)
            
            if create_outfit_image(garment_path, outfit_path, coord_filename, base_filename):
                success_count += 1
        
        logger.info(f"自动生成搭配推荐完成: {garment_filename}, 成功生成 {success_count} 套搭配")
        return success_count > 0
        
    except Exception as e:
        logger.error(f"自动生成搭配推荐失败: {e}")
        return False

@csrf_exempt
def refresh_outfit_recommendations(request):
    """手动刷新指定衣物的搭配推荐"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            garment_filename = data.get('garment_filename')
            
            if not garment_filename:
                return JsonResponse({'success': False, 'error': '缺少衣物文件名'})
            
            logger.info(f"手动刷新衣物搭配推荐: {garment_filename}")
            
            # 1. 获取衣物图片下载链接
            garment_path = settings.SEAFILE_CLOSET_DIR + garment_filename
            img_link = safe_seafile_download_url(garment_path)
            if not img_link:
                return JsonResponse({'success': False, 'error': '无法获取衣物图片链接'})
            
            # 2. 获取衣柜JSON内容
            closet_json_path = settings.SEAFILE_CLOSET_DIR + 'closet.json'
            closet_data = seafile_read_json(closet_json_path)
            if not closet_data:
                return JsonResponse({'success': False, 'error': '无法获取衣柜数据'})
            
            closet_json_str = json.dumps(closet_data, ensure_ascii=False)
            
            # 3. 调用Coze获取搭配推荐
            recommendation_result = call_coze_outfit_recommendation(img_link, closet_json_str)
            if not recommendation_result:
                return JsonResponse({'success': False, 'error': '获取搭配推荐失败'})
            
            # 4. 解析搭配推荐
            outfit_garments = parse_outfit_recommendation(recommendation_result, garment_filename)
            if not outfit_garments:
                return JsonResponse({
                    'success': False, 
                    'error': '暂未找到合适的搭配，请稍后再试',
                    'no_outfits': True
                })
            
            # 5. 创建搭配图片
            base_filename = os.path.splitext(garment_filename)[0]
            recoms_dir = os.path.join(settings.BASE_DIR, 'static', 'recoms', base_filename)
            
            # 检查目录状态并处理
            if os.path.exists(recoms_dir):
                # 目录存在，检查现有文件
                existing_files = [f for f in os.listdir(recoms_dir) if f.endswith(('.jpg', '.png', '.jpeg'))]
                if existing_files:
                    logger.info(f"发现现有搭配文件，更新编号: {recoms_dir}")
                    print(f"=== 更新搭配文件编号 ===")
                    print(f"目录路径: {recoms_dir}")
                    print(f"现有文件: {existing_files}")
                    
                    # 分析现有文件，找到最大的COORD编号
                    max_coord_number = 0
                    coord_files = []
                    fit_files = []
                    
                    for file in existing_files:
                        if 'COORD' in file and not file.endswith('_FIT.jpg'):
                            # 提取COORD编号
                            import re
                            coord_match = re.search(r'COORD(\d+)', file)
                            if coord_match:
                                coord_number = int(coord_match.group(1))
                                max_coord_number = max(max_coord_number, coord_number)
                                coord_files.append(file)
                        elif file.endswith('_FIT.jpg'):
                            fit_files.append(file)
                    
                    # 删除所有现有文件（包括试穿图像）
                    for file in existing_files:
                        file_path = os.path.join(recoms_dir, file)
                        try:
                            os.remove(file_path)
                            print(f"删除文件: {file}")
                        except Exception as e:
                            logger.error(f"删除文件失败 {file}: {e}")
                            print(f"删除文件失败 {file}: {e}")
                    
                    print(f"=== 目录清空完成，最大COORD编号: {max_coord_number} ===")
                else:
                    logger.info(f"搭配目录为空，无需清空: {recoms_dir}")
                    print(f"=== 搭配目录为空，无需清空 ===")
            else:
                # 目录不存在，创建目录
                logger.info(f"创建新的搭配目录: {recoms_dir}")
                print(f"=== 创建新的搭配目录 ===")
                print(f"目录路径: {recoms_dir}")
                os.makedirs(recoms_dir)
                print(f"=== 目录创建完成 ===")
            
            created_outfits = []
            # 获取当前目录中最大的COORD编号
            max_coord_number = 0
            if os.path.exists(recoms_dir):
                existing_files = [f for f in os.listdir(recoms_dir) if f.endswith(('.jpg', '.png', '.jpeg'))]
                for file in existing_files:
                    if 'COORD' in file and not file.endswith('_FIT.jpg'):
                        import re
                        coord_match = re.search(r'COORD(\d+)', file)
                        if coord_match:
                            coord_number = int(coord_match.group(1))
                            max_coord_number = max(max_coord_number, coord_number)
            
            for i, outfit_garment in enumerate(outfit_garments[:2]):
                print(f"=== 处理第 {i+1} 套搭配 ===")
                print(f"搭配衣物名称: {outfit_garment}")
                
                # 构造搭配衣物文件名
                outfit_filename = f"{outfit_garment}.jpg"
                outfit_path = settings.SEAFILE_CLOSET_DIR + outfit_filename
                print(f"构造的文件路径: {outfit_path}")
                print(f"正在请求图片: {outfit_filename}")
                
                # 创建搭配图片，使用更新的编号
                new_coord_number = max_coord_number + i + 1
                coord_filename = f"{base_filename}-COORD{new_coord_number}.jpg"
                coord_path = os.path.join(recoms_dir, coord_filename)
                print(f"搭配图片文件名: {coord_filename}")
                
                print(f"=== 开始创建搭配图片 ===")
                if create_outfit_image(garment_path, outfit_path, coord_filename, base_filename):
                    print(f"=== 搭配图片创建成功 ===")
                    created_outfits.append({
                        'coord_filename': coord_filename,
                        'coord_path': f'/static/recoms/{base_filename}/{coord_filename}'
                    })
                else:
                    print(f"=== 搭配图片创建失败 ===")
            
            if created_outfits:
                return JsonResponse({
                    'success': True,
                    'outfits': created_outfits,
                    'message': f'成功生成 {len(created_outfits)} 套搭配推荐'
                })
            else:
                return JsonResponse({'success': False, 'error': '搭配图片生成失败'})
                
        except Exception as e:
            logger.error(f"刷新搭配推荐失败: {e}")
            return JsonResponse({'success': False, 'error': f'刷新搭配推荐失败: {str(e)}'})
    
    return JsonResponse({'success': False, 'error': '只支持POST请求'})

@csrf_exempt
def generate_try_on_image(request):
    """为搭配图片生成试穿效果"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            coord_filename = data.get('coord_filename')
            base_filename = data.get('base_filename')
            
            if not coord_filename or not base_filename:
                return JsonResponse({'success': False, 'error': '缺少必要参数'})
            
            logger.info(f"开始为搭配图片生成试穿效果: {coord_filename}")
            
            # 1. 获取默认用户信息
            default_user_response = get_default_user(request)
            if default_user_response.status_code != 200:
                return JsonResponse({'success': False, 'error': '无法获取默认用户信息'})
            
            default_user_data = json.loads(default_user_response.content)
            if not default_user_data.get('success'):
                return JsonResponse({'success': False, 'error': '未设置默认用户，请先在个人页面设置默认用户'})
            
            default_user = default_user_data.get('default_user')
            if not default_user or not default_user.get('photo_url'):
                return JsonResponse({'success': False, 'error': '默认用户没有上传形体图片'})
            
            # 2. 获取搭配图片路径
            coord_path = f'/static/recoms/{base_filename}/{coord_filename}'
            coord_full_path = os.path.join(settings.BASE_DIR, 'static', 'recoms', base_filename, coord_filename)
            
            if not os.path.exists(coord_full_path):
                return JsonResponse({'success': False, 'error': '搭配图片不存在'})
            
            # 3. 获取用户形体图片
            user_photo_url = default_user.get('photo_url')
            user_photo_path = os.path.join(settings.BASE_DIR, user_photo_url.lstrip('/'))
            
            if not os.path.exists(user_photo_path):
                return JsonResponse({'success': False, 'error': '用户形体图片不存在'})
            
            # 4. 调用试穿API
            try:
                # 读取图片文件并转换为base64
                with open(user_photo_path, 'rb') as human_file:
                    human_data = human_file.read()
                
                with open(coord_full_path, 'rb') as clothing_file:
                    clothing_data = clothing_file.read()
                
                # 转换为base64
                human_b64 = base64.b64encode(human_data).decode('utf-8')
                clothing_b64 = base64.b64encode(clothing_data).decode('utf-8')
                
                # 调用试穿处理
                result = send_socket_request(human_b64, clothing_b64, server_ip='127.0.0.1', server_port=8899)
                
                if "error" in result:
                    return JsonResponse({'success': False, 'error': result['error']})
                
                # 5. 保存试穿图像
                if result.get("gen_image"):
                    # 生成试穿图像文件名
                    fit_filename = coord_filename.replace('.jpg', '_FIT.jpg')
                    fit_path = os.path.join(settings.BASE_DIR, 'static', 'recoms', base_filename, fit_filename)
                    
                    # 将base64转换为图片并保存
                    image_data = base64.b64decode(result["gen_image"])
                    with open(fit_path, 'wb') as f:
                        f.write(image_data)
                    
                    logger.info(f"试穿图像保存成功: {fit_path}")
                    
                    return JsonResponse({
                        'success': True,
                        'fit_filename': fit_filename,
                        'fit_path': f'/static/recoms/{base_filename}/{fit_filename}',
                        'message': '试穿图像生成成功'
                    })
                else:
                    return JsonResponse({'success': False, 'error': '试穿图像生成失败'})
                    
            except Exception as e:
                logger.error(f"试穿图像生成失败: {e}")
                return JsonResponse({'success': False, 'error': f'试穿图像生成失败: {str(e)}'})
                
        except Exception as e:
            logger.error(f"生成试穿效果失败: {e}")
            return JsonResponse({'success': False, 'error': f'生成试穿效果失败: {str(e)}'})
    
    return JsonResponse({'success': False, 'error': '只支持POST请求'})

@csrf_exempt
def get_closet_data(request):
    """获取衣柜数据用于自定义试穿"""
    try:
        logger.info("开始获取衣柜数据")
        closet_data = load_closet_json()
        logger.info(f"衣柜数据: {closet_data}")
        
        if not closet_data:
            logger.error("衣柜数据为空")
            return JsonResponse({'success': False, 'error': '无法获取衣柜数据'})
        
        # 按衣物类型分类
        upper_garments = []
        lower_garments = []
        
        # 遍历衣柜数据，结构是 {filename: file_info}
        for filename, file_info in closet_data.items():
            # 过滤非图片文件
            if not filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
                continue
                
            # 获取衣物类型
            clothing_type = file_info.get('type', '').upper()
            logger.info(f"处理衣物: {filename}, 类型: {clothing_type}")
            
            # 获取云端图片URL
            file_path = settings.SEAFILE_CLOSET_DIR + filename
            image_url = safe_seafile_download_url(file_path)
            
            if not image_url:
                logger.warning(f"无法获取图片URL: {file_path}")
                continue
            
            # 构造图片信息
            image_info = {
                'filename': filename,
                'url': image_url,
                'category': clothing_type,
                'remark': file_info.get('features', '')
            }
            
            # 根据衣物类型分类
            if is_upper_garment(clothing_type):
                upper_garments.append(image_info)
                logger.info(f"添加上衣: {filename}")
            elif is_lower_garment(clothing_type):
                lower_garments.append(image_info)
                logger.info(f"添加下装: {filename}")
        
        logger.info(f"上衣数量: {len(upper_garments)}, 下装数量: {len(lower_garments)}")
        
        return JsonResponse({
            'success': True,
            'upper_garments': upper_garments,
            'lower_garments': lower_garments
        })
        
    except Exception as e:
        logger.error(f"获取衣柜数据失败: {e}")
        return JsonResponse({'success': False, 'error': f'获取衣柜数据失败: {str(e)}'})

@csrf_exempt
def get_users_for_try_on(request):
    """获取用户列表用于自定义试穿"""
    try:
        # 直接从/static/userinf目录读取用户信息
        userinf_dir = os.path.join(settings.BASE_DIR, 'static', 'userinf')
        users = []
        default_user = None
        
        if os.path.exists(userinf_dir):
            for filename in os.listdir(userinf_dir):
                if filename.endswith('.json'):
                    json_path = os.path.join(userinf_dir, filename)
                    try:
                        with open(json_path, 'r', encoding='utf-8') as f:
                            user_data = json.load(f)
                            
                        # 构建用户信息
                        user_info = {
                            'id': user_data.get('id'),
                            'name': user_data.get('name', '未知用户'),
                            'photo_url': f'/static/userinf/{filename.replace(".json", ".jpg")}',
                            'is_default': user_data.get('is_default', False)
                        }
                        
                        users.append(user_info)
                        
                        # 检查是否为默认用户
                        if user_data.get('is_default', False):
                            default_user = user_info
                            
                    except Exception as e:
                        logger.error(f"读取用户文件失败 {filename}: {e}")
                        continue
        
        return JsonResponse({
            'success': True,
            'users': users,
            'default_user': default_user
        })
        
    except Exception as e:
        logger.error(f"获取用户列表失败: {e}")
        return JsonResponse({'success': False, 'error': f'获取用户列表失败: {str(e)}'})

def custom_try_on(request):
    """自定义试穿"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            upper_garment = data.get('upper_garment')
            lower_garment = data.get('lower_garment')
            user_id = data.get('user_id')
            
            if not upper_garment or not lower_garment:
                return JsonResponse({'success': False, 'error': '请选择上衣和下装'})
            
            logger.info(f"开始自定义试穿: 上衣={upper_garment}, 下装={lower_garment}, 用户={user_id}")
            
            # 1. 获取用户信息
            userinf_dir = os.path.join(settings.BASE_DIR, 'static', 'userinf')
            selected_user = None
            
            if user_id:
                # 获取指定用户
                for filename in os.listdir(userinf_dir):
                    if filename.endswith('.json'):
                        json_path = os.path.join(userinf_dir, filename)
                        try:
                            with open(json_path, 'r', encoding='utf-8') as f:
                                user_data = json.load(f)
                                
                            if user_data.get('id') == user_id:
                                selected_user = {
                                    'id': user_data.get('id'),
                                    'name': user_data.get('name', '未知用户'),
                                    'photo_url': f'/static/userinf/{filename.replace(".json", ".jpg")}'
                                }
                                break
                        except Exception as e:
                            logger.error(f"读取用户文件失败 {filename}: {e}")
                            continue
            else:
                # 使用默认用户
                for filename in os.listdir(userinf_dir):
                    if filename.endswith('.json'):
                        json_path = os.path.join(userinf_dir, filename)
                        try:
                            with open(json_path, 'r', encoding='utf-8') as f:
                                user_data = json.load(f)
                                
                            if user_data.get('is_default', False):
                                selected_user = {
                                    'id': user_data.get('id'),
                                    'name': user_data.get('name', '未知用户'),
                                    'photo_url': f'/static/userinf/{filename.replace(".json", ".jpg")}'
                                }
                                break
                        except Exception as e:
                            logger.error(f"读取用户文件失败 {filename}: {e}")
                            continue
            
            if not selected_user or not selected_user.get('photo_url'):
                return JsonResponse({'success': False, 'error': '用户没有上传形体图片，请先在个人页面设置用户信息'})
            
            user_photo_url = selected_user.get('photo_url')
            
            # 2. 获取衣物图片路径
            closet_data = load_closet_json()
            if not closet_data:
                return JsonResponse({'success': False, 'error': '无法获取衣柜数据'})
            
            # 查找上衣和下装
            upper_path = None
            lower_path = None
            
            # 检查是否为上传的衣物
            if upper_garment.startswith('processed_uploaded_'):
                # 上传的衣物，直接使用本地路径
                upper_path = f'/temp/{upper_garment}'
            else:
                # 衣柜中的衣物，从云端获取
                for filename, file_info in closet_data.items():
                    if filename == upper_garment:
                        file_path = settings.SEAFILE_CLOSET_DIR + filename
                        upper_path = safe_seafile_download_url(file_path)
                        break
            
            if lower_garment.startswith('processed_uploaded_'):
                # 上传的衣物，直接使用本地路径
                lower_path = f'/temp/{lower_garment}'
            else:
                # 衣柜中的衣物，从云端获取
                for filename, file_info in closet_data.items():
                    if filename == lower_garment:
                        file_path = settings.SEAFILE_CLOSET_DIR + filename
                        lower_path = safe_seafile_download_url(file_path)
                        break
            
            if not upper_path or not lower_path:
                return JsonResponse({'success': False, 'error': '衣物图片不存在'})
            
            # 3. 下载并拼接衣物图片
            try:
                from PIL import Image
                import requests
                from io import BytesIO
                
                # 处理上衣图片
                if upper_path.startswith('/static/') or upper_path.startswith('/temp/'):
                    # 本地路径
                    upper_full_path = os.path.join(settings.BASE_DIR, upper_path.lstrip('/'))
                    if not os.path.exists(upper_full_path):
                        return JsonResponse({'success': False, 'error': f'上衣图片不存在: {upper_full_path}'})
                    img1 = Image.open(upper_full_path)
                elif upper_path.startswith('http'):
                    # 远程URL
                    upper_response = requests.get(upper_path)
                    if upper_response.status_code != 200:
                        return JsonResponse({'success': False, 'error': '无法下载上衣图片'})
                    img1 = Image.open(BytesIO(upper_response.content))
                else:
                    return JsonResponse({'success': False, 'error': f'无效的上衣图片路径: {upper_path}'})
                
                # 处理下装图片
                if lower_path.startswith('/static/') or lower_path.startswith('/temp/'):
                    # 本地路径
                    lower_full_path = os.path.join(settings.BASE_DIR, lower_path.lstrip('/'))
                    if not os.path.exists(lower_full_path):
                        return JsonResponse({'success': False, 'error': f'下装图片不存在: {lower_full_path}'})
                    img2 = Image.open(lower_full_path)
                elif lower_path.startswith('http'):
                    # 远程URL
                    lower_response = requests.get(lower_path)
                    if lower_response.status_code != 200:
                        return JsonResponse({'success': False, 'error': '无法下载下装图片'})
                    img2 = Image.open(BytesIO(lower_response.content))
                else:
                    return JsonResponse({'success': False, 'error': f'无效的下装图片路径: {lower_path}'})
                
                # 拼接图片
                combined_clothing = concat_images_vertically(img1, img2)
                
                # 保存拼接后的图片到临时文件
                temp_dir = os.path.join(settings.BASE_DIR, 'temp')
                os.makedirs(temp_dir, exist_ok=True)
                temp_filename = f"combined_{int(time.time())}.jpg"
                temp_path = os.path.join(temp_dir, temp_filename)
                combined_clothing.save(temp_path, 'JPEG')
                
                # 4. 获取用户形体图片
                user_photo_path = os.path.join(settings.BASE_DIR, user_photo_url.lstrip('/'))
                if not os.path.exists(user_photo_path):
                    return JsonResponse({'success': False, 'error': '用户形体图片不存在'})
                
                # 5. 调用试穿API
                try:
                    # 读取图片文件并转换为base64
                    with open(user_photo_path, 'rb') as human_file:
                        human_data = human_file.read()
                    
                    with open(temp_path, 'rb') as clothing_file:
                        clothing_data = clothing_file.read()
                    
                    # 转换为base64
                    human_b64 = base64.b64encode(human_data).decode('utf-8')
                    clothing_b64 = base64.b64encode(clothing_data).decode('utf-8')
                    
                    # 调用试穿处理
                    result = send_socket_request(human_b64, clothing_b64, server_ip='127.0.0.1', server_port=8899)
                    
                    if "error" in result:
                        return JsonResponse({'success': False, 'error': result['error']})
                    
                    # 6. 保存试穿图像
                    if result.get("gen_image"):
                        # 生成试穿图像文件名
                        fit_filename = f"custom_try_on_{int(time.time())}.jpg"
                        fit_path = os.path.join(settings.BASE_DIR, 'static', 'temp', fit_filename)
                        
                        # 确保目录存在
                        os.makedirs(os.path.dirname(fit_path), exist_ok=True)
                        
                        # 将base64转换为图片并保存
                        image_data = base64.b64decode(result["gen_image"])
                        with open(fit_path, 'wb') as f:
                            f.write(image_data)
                        
                        # 清理临时文件
                        if os.path.exists(temp_path):
                            os.remove(temp_path)
                        
                        logger.info(f"自定义试穿图像保存成功: {fit_path}")
                        
                        return JsonResponse({
                            'success': True,
                            'fit_filename': fit_filename,
                            'fit_path': f'/static/temp/{fit_filename}',
                            'message': '自定义试穿图像生成成功'
                        })
                    else:
                        return JsonResponse({'success': False, 'error': '试穿图像生成失败'})
                        
                except Exception as e:
                    logger.error(f"自定义试穿图像生成失败: {e}")
                    return JsonResponse({'success': False, 'error': f'试穿图像生成失败: {str(e)}'})
                    
            except Exception as e:
                logger.error(f"拼接衣物图片失败: {e}")
                return JsonResponse({'success': False, 'error': f'拼接衣物图片失败: {str(e)}'})
                
        except Exception as e:
            logger.error(f"自定义试穿失败: {e}")
            return JsonResponse({'success': False, 'error': f'自定义试穿失败: {str(e)}'})
    
    return JsonResponse({'success': False, 'error': '只支持POST请求'})

@csrf_exempt
def test_closet_data(request):
    """测试衣柜数据加载"""
    try:
        logger.info("=== 开始测试衣柜数据加载 ===")
        
        # 测试load_closet_json
        closet_data = load_closet_json()
        logger.info(f"load_closet_json结果: {closet_data}")
        
        if not closet_data:
            return JsonResponse({
                'success': False,
                'error': '衣柜数据为空',
                'closet_data': None
            })
        
        # 测试数据结构和内容
        sample_items = []
        for filename, file_info in list(closet_data.items())[:5]:  # 只取前5个作为样本
            sample_items.append({
                'filename': filename,
                'file_info': file_info
            })
        
        return JsonResponse({
            'success': True,
            'total_items': len(closet_data),
            'sample_items': sample_items,
            'closet_data_keys': list(closet_data.keys())
        })
        
    except Exception as e:
        logger.error(f"测试衣柜数据失败: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

@csrf_exempt
def process_uploaded_garment(request):
    """处理用户上传的衣物图片"""
    if request.method == 'POST':
        try:
            # 获取上传的文件
            uploaded_file = request.FILES.get('image')
            garment_type = request.POST.get('type')  # 'upper' 或 'lower'
            
            if not uploaded_file:
                return JsonResponse({'success': False, 'error': '没有上传文件'})
            
            if not garment_type:
                return JsonResponse({'success': False, 'error': '未指定衣物类型'})
            
            logger.info(f"处理上传的衣物: 类型={garment_type}, 文件名={uploaded_file.name}")
            
            # 生成唯一文件名
            timestamp = int(time.time())
            original_filename = uploaded_file.name
            file_ext = os.path.splitext(original_filename)[1].lower()
            if file_ext not in ['.jpg', '.jpeg', '.png', '.gif']:
                file_ext = '.jpg'
            
            filename = f"uploaded_{garment_type}_{timestamp}{file_ext}"
            
            # 保存原始文件到临时目录
            temp_dir = os.path.join(settings.BASE_DIR, 'temp')
            os.makedirs(temp_dir, exist_ok=True)
            temp_path = os.path.join(temp_dir, filename)
            
            with open(temp_path, 'wb') as f:
                for chunk in uploaded_file.chunks():
                    f.write(chunk)
            
            # 处理图片：移除背景、添加白色背景、裁剪
            try:
                from PIL import Image
                
                # 打开图片
                img = Image.open(temp_path)
                
                # 1. 移除背景
                img_no_bg = remove_background(img)
                
                # 2. 添加白色背景
                img_with_white = add_white_background(img_no_bg)
                
                # 3. 裁剪非白色内容
                img_cropped = crop_non_white_content(img_with_white)
                
                # 保存处理后的图片
                processed_filename = f"processed_{filename}"
                processed_path = os.path.join(temp_dir, processed_filename)
                img_cropped.save(processed_path, 'JPEG', quality=95)
                
                # 生成访问URL
                processed_url = f'/temp/{processed_filename}'
                
                logger.info(f"衣物处理完成: {processed_filename}")
                
                return JsonResponse({
                    'success': True,
                    'filename': processed_filename,
                    'processed_url': processed_url,
                    'message': '衣物处理成功'
                })
                
            except Exception as e:
                logger.error(f"图片处理失败: {e}")
                return JsonResponse({'success': False, 'error': f'图片处理失败: {str(e)}'})
                
        except Exception as e:
            logger.error(f"处理上传衣物失败: {e}")
            return JsonResponse({'success': False, 'error': f'处理失败: {str(e)}'})
    
    return JsonResponse({'success': False, 'error': '只支持POST请求'})

def backup_closet_json():
    """备份closet.json文件到closet_copy.json"""
    try:
        source_path = settings.SEAFILE_CLOSET_DIR + 'closet.json'
        backup_path = settings.SEAFILE_CLOSET_DIR + 'closet_copy.json'
        
        # 读取当前closet.json
        current_data = seafile_read_json(source_path)
        if current_data is None:
            logger.warning("无法读取closet.json进行备份")
            return False
        
        # 写入备份文件
        success = seafile_write_json_direct(backup_path, current_data)
        if success:
            logger.info("closet.json备份成功")
            return True
        else:
            logger.error("closet.json备份失败")
            return False
            
    except Exception as e:
        logger.error(f"备份closet.json失败: {e}")
        return False

def restore_closet_json():
    """从closet_copy.json恢复closet.json"""
    try:
        source_path = settings.SEAFILE_CLOSET_DIR + 'closet_copy.json'
        target_path = settings.SEAFILE_CLOSET_DIR + 'closet.json'
        
        # 读取备份文件
        backup_data = seafile_read_json(source_path)
        if backup_data is None:
            logger.error("无法读取备份文件")
            return False
        
        # 恢复原文件
        success = seafile_write_json_direct(target_path, backup_data)
        if success:
            logger.info("closet.json恢复成功")
            return True
        else:
            logger.error("closet.json恢复失败")
            return False
            
    except Exception as e:
        logger.error(f"恢复closet.json失败: {e}")
        return False

def safe_save_closet_json(closet_data):
    """安全保存closet.json，包含备份机制"""
    try:
        # 1. 先备份当前数据
        if not backup_closet_json():
            logger.error("备份失败，取消保存操作")
            return False
        
        # 2. 尝试保存新数据
        file_path = settings.SEAFILE_CLOSET_DIR + 'closet.json'
        success = seafile_write_json_direct(file_path, closet_data)
        
        if success:
            logger.info("closet.json安全保存成功")
            return True
        else:
            logger.error("保存失败，尝试恢复备份")
            # 3. 如果保存失败，恢复备份
            if restore_closet_json():
                logger.info("已从备份恢复closet.json")
            else:
                logger.error("恢复备份也失败了！")
            return False
            
    except Exception as e:
        logger.error(f"安全保存closet.json失败: {e}")
        # 尝试恢复备份
        try:
            restore_closet_json()
        except:
            logger.error("恢复备份也失败了！")
        return False

@csrf_exempt
def test_backup_system(request):
    """测试备份系统功能"""
    try:
        # 1. 测试备份功能
        backup_success = backup_closet_json()
        
        # 2. 读取当前closet.json
        current_data = load_closet_json()
        
        # 3. 读取备份文件
        backup_path = settings.SEAFILE_CLOSET_DIR + 'closet_copy.json'
        backup_data = seafile_read_json(backup_path)
        
        # 4. 比较数据
        data_match = current_data == backup_data if backup_data else False
        
        return JsonResponse({
            'success': True,
            'backup_success': backup_success,
            'data_match': data_match,
            'current_data_count': len(current_data),
            'backup_data_count': len(backup_data) if backup_data else 0,
            'message': '备份系统测试完成'
        })
        
    except Exception as e:
        logger.error(f"测试备份系统失败: {e}")
        return JsonResponse({
            'success': False,
            'error': f'测试失败: {str(e)}'
        })

@csrf_exempt
def restore_from_backup(request):
    """从备份恢复closet.json"""
    try:
        if request.method == 'POST':
            # 执行恢复操作
            restore_success = restore_closet_json()
            
            if restore_success:
                # 读取恢复后的数据
                restored_data = load_closet_json()
                
                return JsonResponse({
                    'success': True,
                    'restore_success': True,
                    'restored_data_count': len(restored_data),
                    'message': '已从备份恢复closet.json'
                })
            else:
                return JsonResponse({
                    'success': False,
                    'restore_success': False,
                    'error': '恢复备份失败'
                })
        else:
            return JsonResponse({
                'success': False,
                'error': '只支持POST请求'
            })
            
    except Exception as e:
        logger.error(f"恢复备份失败: {e}")
        return JsonResponse({
            'success': False,
            'error': f'恢复失败: {str(e)}'
        })

def map_classification_to_category(clothing_type):
    """
    将AI分类结果映射到closet页面的分类导航栏
    """
    # 分类映射表
    category_mapping = {
        # T恤相关
        'T恤': 'T恤',
        'T-SHIRT': 'T恤',
        'T恤衫': 'T恤',
        '短袖': 'T恤',
        '圆领T恤': 'T恤',
        'V领T恤': 'T恤',
        
        # 外套相关
        '外套': '外套',
        'COAT': '外套',
        '大衣': '外套',
        '风衣': '外套',
        '夹克': '外套',
        '羽绒服': '外套',
        '西装外套': '外套',
        
        # 连衣裙相关
        '连衣裙': '连衣裙',
        'DRESS': '连衣裙',
        '裙子': '连衣裙',
        '连身裙': '连衣裙',
        '礼服': '连衣裙',
        
        # 开衫相关
        '开衫': '开衫',
        'CARDIGAN': '开衫',
        '针织开衫': '开衫',
        '毛衣开衫': '开衫',
        
        # 长裤相关
        '长裤': '长裤',
        'TROUSERS': '长裤',
        '裤子': '长裤',
        '牛仔裤': '长裤',
        '休闲裤': '长裤',
        '西裤': '长裤',
        
        # 衬衫相关
        '衬衫': '衬衫',
        'SHIRT': '衬衫',
        '衬衣': '衬衫',
        '商务衬衫': '衬衫',
        '休闲衬衫': '衬衫',
        
        # 短裙相关
        '短裙': '短裙',
        'SKIRT': '短裙',
        '半身裙': '短裙',
        'A字裙': '短裙',
        '百褶裙': '短裙',
        
        # 正装相关
        '正装': '正装',
        'SUIT': '正装',
        '西装': '正装',
        '职业装': '正装',
        '商务装': '正装',
        
        # 短裤相关
        '短裤': '短裤',
        'SHORTS': '短裤',
        '运动短裤': '短裤',
        '休闲短裤': '短裤',
        
        # 卫衣相关
        '卫衣': '卫衣',
        'SWEATSHIRT': '卫衣',
        '连帽卫衣': '卫衣',
        '运动卫衣': '卫衣',
        '休闲卫衣': '卫衣',
    }
    
    # 清理输入的分类名称
    cleaned_type = str(clothing_type).strip().upper()
    
    # 尝试直接匹配
    if cleaned_type in category_mapping:
        return category_mapping[cleaned_type]
    
    # 尝试模糊匹配
    for key, value in category_mapping.items():
        if key.upper() in cleaned_type or cleaned_type in key.upper():
            return value
    
    # 如果都没有匹配到，根据关键词判断
    if any(keyword in cleaned_type for keyword in ['T恤', 'T-SHIRT', '短袖']):
        return 'T恤'
    elif any(keyword in cleaned_type for keyword in ['外套', 'COAT', '大衣', '风衣']):
        return '外套'
    elif any(keyword in cleaned_type for keyword in ['连衣裙', 'DRESS', '裙子']):
        return '连衣裙'
    elif any(keyword in cleaned_type for keyword in ['开衫', 'CARDIGAN', '针织']):
        return '开衫'
    elif any(keyword in cleaned_type for keyword in ['长裤', 'TROUSERS', '裤子', '牛仔裤']):
        return '长裤'
    elif any(keyword in cleaned_type for keyword in ['衬衫', 'SHIRT', '衬衣']):
        return '衬衫'
    elif any(keyword in cleaned_type for keyword in ['短裙', 'SKIRT', '半身裙']):
        return '短裙'
    elif any(keyword in cleaned_type for keyword in ['正装', 'SUIT', '西装']):
        return '正装'
    elif any(keyword in cleaned_type for keyword in ['短裤', 'SHORTS']):
        return '短裤'
    elif any(keyword in cleaned_type for keyword in ['卫衣', 'SWEATSHIRT', '连帽']):
        return '卫衣'
    
    # 默认返回T恤
    logger.warning(f"无法映射分类 '{clothing_type}'，默认返回T恤")
    return 'T恤'

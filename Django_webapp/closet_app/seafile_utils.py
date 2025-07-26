#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Seafile工具模块
提供统一的Seafile操作函数，确保正确处理API返回的数据结构
"""

import os
import requests
import logging
from django.conf import settings

logger = logging.getLogger(__name__)

def seafile_headers():
    """获取Seafile API请求头"""
    return {'Authorization': f'Token {settings.SEAFILE_TOKEN}'}

def safe_seafile_list(dir_path):
    """
    安全地获取Seafile目录列表
    返回格式统一的文件列表
    """
    url = f"{settings.SEAFILE_API_URL}/repos/{settings.SEAFILE_LIBRARY_ID}/dir/"
    params = {'p': dir_path}
    
    try:
        resp = requests.get(url, headers=seafile_headers(), params=params)
        if resp.status_code == 200:
            data = resp.json()
            # 处理不同的返回格式
            if isinstance(data, dict):
                return data.get('dirent_list', [])
            elif isinstance(data, list):
                return data
            else:
                logger.error(f"未知的API返回格式: {type(data)}")
                return []
        else:
            logger.error(f"获取目录列表失败: {resp.status_code} - {resp.text}")
            return []
    except Exception as e:
        logger.error(f"获取目录列表异常: {e}")
        return []

def safe_seafile_upload_file(local_path, remote_dir):
    """
    安全地上传文件到Seafile
    """
    try:
        # 获取上传链接
        upload_link_url = f"{settings.SEAFILE_API_URL}/repos/{settings.SEAFILE_LIBRARY_ID}/upload-link/?p={remote_dir}"
        resp = requests.get(upload_link_url, headers=seafile_headers())
        
        if resp.status_code != 200:
            logger.error(f"获取上传链接失败: {resp.text}")
            return False
        
        try:
            upload_link = resp.json()
        except Exception as e:
            logger.error(f"解析上传链接JSON失败: {e}")
            return False
        
        # 上传文件
        filename = os.path.basename(local_path)
        with open(local_path, 'rb') as f:
            files = {'file': (filename, f)}
            data = {'parent_dir': remote_dir}
            upload_resp = requests.post(upload_link, data=data, files=files)
            
            if upload_resp.status_code == 200:
                logger.info(f"上传成功: {filename} -> {remote_dir}")
                return True
            else:
                logger.error(f"上传失败: {filename} -> {remote_dir}, 错误: {upload_resp.text}")
                return False
                
    except Exception as e:
        logger.error(f"上传文件异常: {e}")
        return False

def safe_seafile_delete(file_path):
    """
    安全地删除Seafile文件
    """
    try:
        url = f"{settings.SEAFILE_API_URL}/repos/{settings.SEAFILE_LIBRARY_ID}/file/"
        params = {'p': file_path}
        resp = requests.delete(url, headers=seafile_headers(), params=params)
        return resp.status_code == 200
    except Exception as e:
        logger.error(f"删除文件异常: {e}")
        return False

def safe_seafile_download_url(file_path):
    """
    安全地获取Seafile文件下载链接
    """
    try:
        url = f"{settings.SEAFILE_API_URL}/repos/{settings.SEAFILE_LIBRARY_ID}/file/"
        params = {'p': file_path}
        resp = requests.get(url, headers=seafile_headers(), params=params)
        if resp.status_code == 200:
            data = resp.json()
            # 处理不同的返回格式
            if isinstance(data, dict):
                return data.get('url')
            elif isinstance(data, str):
                # 如果返回的是字符串，可能是直接的URL
                return data
            else:
                logger.error(f"获取下载链接返回格式错误: {type(data)}")
                return None
        return None
    except Exception as e:
        logger.error(f"获取下载链接异常: {e}")
        return None

def filter_files_by_type(files, file_type='file', extensions=None):
    """
    过滤文件列表
    Args:
        files: 文件列表
        file_type: 文件类型 ('file' 或 'dir')
        extensions: 文件扩展名列表，如 ['.jpg', '.png']
    """
    if not isinstance(files, list):
        return []
    
    filtered_files = []
    for f in files:
        if not isinstance(f, dict):
            continue
            
        if f.get('type') != file_type:
            continue
            
        if extensions:
            filename = f.get('name', '')
            if not any(filename.endswith(ext) for ext in extensions):
                continue
                
        filtered_files.append(f)
    
    return filtered_files

def get_file_count_by_type(files, file_type='file'):
    """
    获取指定类型的文件数量
    """
    filtered_files = filter_files_by_type(files, file_type)
    return len(filtered_files)

def validate_seafile_response(data, expected_type=None):
    """
    验证Seafile API响应数据
    """
    if expected_type and not isinstance(data, expected_type):
        logger.error(f"API响应类型错误: 期望 {expected_type}, 实际 {type(data)}")
        return False
    return True 
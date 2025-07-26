// 设备适配工具类
class DeviceAdapter {
    constructor() {
        this.deviceInfo = this.getDeviceInfo();
        this.init();
    }

    // 获取设备信息
    getDeviceInfo() {
        const userAgent = navigator.userAgent;
        const screen = window.screen;
        
        return {
            userAgent: userAgent,
            screenWidth: screen.width,
            screenHeight: screen.height,
            pixelRatio: window.devicePixelRatio || 1,
            orientation: screen.orientation ? screen.orientation.type : 'portrait',
            isMobile: /Android|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(userAgent),
            isIOS: /iPad|iPhone|iPod/.test(userAgent),
            isAndroid: /Android/.test(userAgent),
            isTablet: /iPad|Android(?=.*\bMobile\b)(?=.*\bSafari\b)/.test(userAgent),
            isLandscape: window.innerWidth > window.innerHeight
        };
    }

    // 初始化适配
    init() {
        this.setupViewport();
        this.setupSafeArea();
        this.setupOrientationChange();
        this.setupResizeHandler();
        this.applyDeviceSpecificStyles();
    }

    // 设置视口
    setupViewport() {
        const viewport = document.querySelector('meta[name="viewport"]');
        if (viewport) {
            let content = 'width=device-width, initial-scale=1.0, user-scalable=no';
            
            // iOS设备特殊处理
            if (this.deviceInfo.isIOS) {
                content += ', viewport-fit=cover';
            }
            
            viewport.setAttribute('content', content);
        }
    }

    // 设置安全区域
    setupSafeArea() {
        const style = document.createElement('style');
        style.textContent = `
            .safe-area-top {
                padding-top: env(safe-area-inset-top);
            }
            .safe-area-bottom {
                padding-bottom: env(safe-area-inset-bottom);
            }
            .safe-area-left {
                padding-left: env(safe-area-inset-left);
            }
            .safe-area-right {
                padding-right: env(safe-area-inset-right);
            }
        `;
        document.head.appendChild(style);
    }

    // 监听方向变化
    setupOrientationChange() {
        window.addEventListener('orientationchange', () => {
            setTimeout(() => {
                this.deviceInfo.isLandscape = window.innerWidth > window.innerHeight;
                this.deviceInfo.orientation = this.deviceInfo.isLandscape ? 'landscape' : 'portrait';
                this.applyDeviceSpecificStyles();
                this.adjustLayout();
            }, 100);
        });
    }

    // 监听窗口大小变化
    setupResizeHandler() {
        let resizeTimeout;
        window.addEventListener('resize', () => {
            clearTimeout(resizeTimeout);
            resizeTimeout = setTimeout(() => {
                this.deviceInfo.screenWidth = window.innerWidth;
                this.deviceInfo.screenHeight = window.innerHeight;
                this.deviceInfo.isLandscape = window.innerWidth > window.innerHeight;
                this.applyDeviceSpecificStyles();
                this.adjustLayout();
            }, 250);
        });
    }

    // 应用设备特定样式
    applyDeviceSpecificStyles() {
        const body = document.body;
        
        // 移除之前的设备类
        body.classList.remove('device-mobile', 'device-tablet', 'device-desktop', 'device-ios', 'device-android');
        
        // 添加设备类
        if (this.deviceInfo.isMobile) {
            body.classList.add('device-mobile');
        } else if (this.deviceInfo.isTablet) {
            body.classList.add('device-tablet');
        } else {
            body.classList.add('device-desktop');
        }
        
        if (this.deviceInfo.isIOS) {
            body.classList.add('device-ios');
        } else if (this.deviceInfo.isAndroid) {
            body.classList.add('device-android');
        }
        
        // 添加方向类
        body.classList.remove('orientation-portrait', 'orientation-landscape');
        body.classList.add(`orientation-${this.deviceInfo.isLandscape ? 'landscape' : 'portrait'}`);
    }

    // 调整布局
    adjustLayout() {
        const frame = document.querySelector('.iphone13-frame');
        if (!frame) return;

        if (this.deviceInfo.isMobile && this.deviceInfo.screenWidth <= 480) {
            // 小屏幕手机
            frame.style.width = '100vw';
            frame.style.height = '100vh';
            frame.style.margin = '0';
            frame.style.borderRadius = '0';
            frame.style.border = 'none';
        } else if (this.deviceInfo.isTablet) {
            // 平板设备
            const aspectRatio = this.deviceInfo.isLandscape ? 4/3 : 3/4;
            const maxWidth = Math.min(window.innerWidth * 0.8, 768);
            const maxHeight = Math.min(window.innerHeight * 0.8, 1024);
            
            if (this.deviceInfo.isLandscape) {
                frame.style.width = `${maxWidth}px`;
                frame.style.height = `${maxWidth / aspectRatio}px`;
            } else {
                frame.style.height = `${maxHeight}px`;
                frame.style.width = `${maxHeight * aspectRatio}px`;
            }
            frame.style.margin = '20px auto';
        } else {
            // 桌面设备保持原样
            frame.style.width = '390px';
            frame.style.height = '844px';
            frame.style.margin = '40px auto';
            frame.style.borderRadius = '40px';
            frame.style.border = '1px solid #ccc';
        }
    }

    // 获取设备类型
    getDeviceType() {
        if (this.deviceInfo.isMobile) {
            return this.deviceInfo.screenWidth <= 480 ? 'small-mobile' : 'large-mobile';
        } else if (this.deviceInfo.isTablet) {
            return 'tablet';
        } else {
            return 'desktop';
        }
    }

    // 获取推荐字体大小
    getRecommendedFontSize(baseSize = 16) {
        const deviceType = this.getDeviceType();
        const scaleFactors = {
            'small-mobile': 0.9,
            'large-mobile': 1.0,
            'tablet': 1.1,
            'desktop': 1.2
        };
        return Math.round(baseSize * scaleFactors[deviceType]);
    }

    // 检测是否支持触摸
    isTouchSupported() {
        return 'ontouchstart' in window || navigator.maxTouchPoints > 0;
    }

    // 获取屏幕密度
    getScreenDensity() {
        return this.deviceInfo.pixelRatio;
    }

    // 优化图片加载
    optimizeImages() {
        const images = document.querySelectorAll('img');
        const density = this.getScreenDensity();
        
        images.forEach(img => {
            if (img.dataset.src) {
                // 根据屏幕密度选择合适分辨率的图片
                if (density >= 2 && img.dataset.src2x) {
                    img.src = img.dataset.src2x;
                } else if (density >= 3 && img.dataset.src3x) {
                    img.src = img.dataset.src3x;
                } else {
                    img.src = img.dataset.src;
                }
            }
        });
    }

    // 设置触摸优化
    setupTouchOptimization() {
        if (this.isTouchSupported()) {
            document.body.classList.add('touch-device');
            
            // 添加触摸反馈
            const touchElements = document.querySelectorAll('button, .clickable, [role="button"]');
            touchElements.forEach(element => {
                element.addEventListener('touchstart', () => {
                    element.style.transform = 'scale(0.95)';
                });
                
                element.addEventListener('touchend', () => {
                    element.style.transform = 'scale(1)';
                });
            });
        }
    }
}

// 初始化设备适配器
document.addEventListener('DOMContentLoaded', () => {
    window.deviceAdapter = new DeviceAdapter();
    
    // 延迟执行一些需要DOM完全加载的操作
    setTimeout(() => {
        window.deviceAdapter.optimizeImages();
        window.deviceAdapter.setupTouchOptimization();
    }, 100);
});

// 导出供其他模块使用
if (typeof module !== 'undefined' && module.exports) {
    module.exports = DeviceAdapter;
} 
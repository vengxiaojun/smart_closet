from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('leffa_process/', views.leffa_process, name='leffa_process'),
    path('speech/', views.speech_function, name='speech_function'),
    path('image/', views.image_function, name='image_function'),
    #path('closet/', views.closet_function, name='closet_function'),
    path('outfit_display/', views.outfit_display_function, name='outfit_display_function'),
    path('clothing_try_on/', views.clothing_try_on_function, name='clothing_try_on_function'),
    path('api/classify/', views.classify_clothing),
    path('api/save_closet_image/', views.save_closet_image),
    path('api/closet_list/', views.closet_list),
    path('api/closet_rename/', views.closet_rename),
    path('closet_delete/', views.closet_delete,name='closet_delete'),
    path('api/body_list/', views.body_list),
    path('api/save_body_image/', views.save_body_image),
    path('api/body_rename/', views.body_rename),
    path('api/test_classify/', views.test_classify),
    path('get_weather/', views.get_weather, name='get_weather'),
    path('closet/', views.closet_function, name='closet'),#前端closet
    path('match/', views.match_function, name='match'), #前端match
    path('profile/', views.profile_function, name='profile'),#前端profile
    path('mirror/', views.mirror_function, name='mirror'),#前端mirror
    path('save_user/', views.save_user, name='save_user'),
    path('load_users/', views.load_users, name='load_users'),
    path('get_user/', views.get_user, name='get_user'),
    path('delete_user/', views.delete_user, name='delete_user'),
    path('set_default_user/', views.set_default_user, name='set_default_user'),
    path('get_default_user/', views.get_default_user, name='get_default_user'),
    path('coze-workflow/', views.coze_workflow, name='coze_workflow'),
    path('test-cloud/', views.test_cloud, name='test_cloud'),
    path('upload_clothes/', views.upload_clothes, name='upload_clothes'),
    path('get_matching_images/', views.get_matching_images, name='get_matching_images'),
    path('api/asr/', views.asr_api, name='asr_api'),
    path('test-users/', views.test_users, name='test_users'),
    path('api/generate_outfit_recommendations/', views.generate_outfit_recommendations, name='generate_outfit_recommendations'),
    path('api/refresh_outfit_recommendations/', views.refresh_outfit_recommendations, name='refresh_outfit_recommendations'),
    path('api/generate_try_on_image/', views.generate_try_on_image, name='generate_try_on_image'),
    path('test-numbering/', views.test_garment_numbering_system, name='test_numbering'),
    path('responsive-test/', views.responsive_test, name='responsive_test'),
    # 自定义试穿相关路由
    path('api/get_closet_data/', views.get_closet_data, name='get_closet_data'),
    path('api/get_users_for_try_on/', views.get_users_for_try_on, name='get_users_for_try_on'),
    path('api/custom_try_on/', views.custom_try_on, name='custom_try_on'),
    path('api/test_closet_data/', views.test_closet_data, name='test_closet_data'),
    path('api/process_uploaded_garment/', views.process_uploaded_garment, name='process_uploaded_garment'),
    path('api/test_backup_system/', views.test_backup_system, name='test_backup_system'),
    path('api/restore_from_backup/', views.restore_from_backup, name='restore_from_backup'),
    
]

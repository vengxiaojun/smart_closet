
"""
This example describes how to use the workflow interface to stream chat.
"""

from cozepy import Coze, TokenAuth, WorkflowEventType

personal_access_token = 'pat_VQjUPkmzVZqbCK0iRv8tfbduNZleH2Si9yJD93PjA8qW3flFqG171wgcRRJNCwf1'
coze_api_base = 'https://api.coze.cn'
workflow_id = '7523138791135559690'

coze = Coze(auth=TokenAuth(token=personal_access_token), base_url=coze_api_base)

stream = coze.workflows.runs.stream(
    workflow_id=workflow_id,
    #parameters={"img": image_url}  # 一定要传入img参数，值是图片URL字符串
    parameters={
    "city": "武汉市"
    }
)

for event in stream:
    if event.event == WorkflowEventType.MESSAGE:
        print("识别结果:", event.message)
    elif event.event == WorkflowEventType.ERROR:
        print("调用错误:", event.error)

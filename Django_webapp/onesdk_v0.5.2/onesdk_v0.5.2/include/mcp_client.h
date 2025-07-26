#ifndef __MCP_CLIENT_H__
#define __MCP_CLIENT_H__

#include <stdio.h>
#include <stdlib.h>
#include <stdbool.h>
#include <string.h>
#include "onesdk.h"
#include "protocols/http.h"
#include "cJSON.h"
#include "onesdk_chat.h"
#include <libwebsockets.h>


// typedef struct _input_schema_s{
//     char *type;
//     char *properties;
//     char *required;//[]string
// }input_schema_t;

typedef struct _tool_s{
    char *name;
    char *description;
    // input_schema_t input_schema;//透传给大模型，不解析
    char *input_schema_raw;
}tool_t;

typedef struct _tools_list_s{
    tool_t *tools;
    int count;
}tools_list_t;


typedef struct _tool_result_content_s{
    char *type;
    char *text;
}tool_result_content_t;


typedef struct _tool_result_s{
    bool isError;
    tool_result_content_t *content;
    int content_count;
}tool_result_t;



typedef struct _sse_message_s{
    int request_id;
    char *result;
}sse_message_t;

typedef struct _mcp_context_s{
    pthread_mutex_t lock;
    http_request_context_t *http_ctx;
    int initialize_request_id;
    bool initialized;
    bool endpoint_got;
    char *endpoint;
    sse_message_t messages;
    char *address;
    int port;
}mcp_context_t;


void mcp_client_init(mcp_context_t *ctx);

void mcp_tools_list_free(tools_list_t *tools_list);


void mcp_tool_result_free(tool_result_t *tool_result);


char *mcp_get_tool_result_text(tool_result_t *tool_result);


mcp_context_t *mcp_ctx_new();

void mcp_receiver_init(mcp_context_t *ctx,const char *ip, int port);

int block_receive_from_sse_server(mcp_context_t *ctx);

void mcp_ctx_free(mcp_context_t *ctx);


tools_list_t *mcp_tools_list(mcp_context_t *ctx);


tool_result_t *mcp_tool_call(mcp_context_t *ctx,const char *name,const char *arguments);



#endif

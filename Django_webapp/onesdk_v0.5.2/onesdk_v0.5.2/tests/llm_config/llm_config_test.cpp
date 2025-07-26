#include "CppUTest/TestHarness.h"
#include "CppUTestExt/MockSupport.h"

extern "C"
{
  #include "CppUTest/TestHarness_c.h"
  #include "aigw/llm.h"
  #include "protocols/http.h"
}

// #define SAMPLE_HTTP_HOST "iot-cn-shanghai.iot.volces.com"
#define SAMPLE_HTTP_HOST "10.249.160.34:9996"
#define SAMPLE_INSTANCE_ID "6784dcf26c8dc8689881e67d"
#define SAMPLE_MQTT_HOST "6784dcf26c8dc8689881e67d.cn-shanghai.iot.volces.com"
#define SAMPLE_DEVICE_NAME "P1-9"
#define SAMPLE_DEVICE_SECRET ""
#define SAMPLE_PRODUCT_KEY "6788bd810f9bad3f8ef674fa"
#define SAMPLE_PRODUCT_SECRET "84d2917973026d49be374ec4"

TEST_GROUP(llm_config) {
    iot_basic_ctx_t *basic_ctx;
    void setup() {
        // 动态分配内存
        basic_ctx = (iot_basic_ctx_t *)cpputest_malloc(sizeof(iot_basic_ctx_t));
        memset(basic_ctx, 0, sizeof(iot_basic_ctx_t));
        basic_ctx->config = (iot_basic_config_t *)cpputest_malloc(sizeof(iot_basic_config_t));
        memset(basic_ctx->config, 0, sizeof(iot_basic_config_t));
        // 初始化结构体成员
        basic_ctx->config->http_host = cpputest_strdup(SAMPLE_HTTP_HOST);
        basic_ctx->config->instance_id = cpputest_strdup(SAMPLE_INSTANCE_ID);
        basic_ctx->config->product_key =cpputest_strdup(SAMPLE_PRODUCT_KEY);
        basic_ctx->config->product_secret =cpputest_strdup(SAMPLE_PRODUCT_SECRET);
        basic_ctx->config->device_name =cpputest_strdup(SAMPLE_DEVICE_NAME);
        basic_ctx->config->device_secret =cpputest_strdup("98cb52e94e437ee407dbed37"); // P1
        basic_ctx->config->auth_type = ONESDK_AUTH_DYNAMIC_NO_PRE_REGISTERED;
    }

    void teardown() {
        onesdk_iot_basic_deinit(basic_ctx);

        mock("llm_config").clear();
        mock().clear();
    }
};

http_response_t *http_request(http_request_context_t *http_context) {
    mock("llm_config").actualCall("http_request");
    char *mock_body = "{\"ResponseMetadata\":{\"Action\":\"GetLLMConfig\",\"Version\":\"2021-12-14\"},\"Result\":{\"URL\":\"http://llm-gateway.vei.gtm.volcdns.com:30506\",\"APIKey\":\"w/LdsxG/MgSAhVGD3WmPng==\"}}\r\n";
    http_response_t *mock_response = (http_response_t *)cpputest_malloc(sizeof(http_response_t));
    memset(mock_response, 0, sizeof(http_response_t));
    mock_response->body_size = strlen(mock_body)+1;
    mock_response->response_body = cpputest_strdup(mock_body);

    http_context->response = mock_response;

    return mock_response;
}

http_request_context_t *new_http_ctx() {
    mock("llm_config").actualCall("new_http_ctx");
    http_request_context_t *http_context = (http_request_context_t *)cpputest_malloc(sizeof(http_request_context_t));
    memset(http_context, 0, sizeof(http_request_context_t));
    return http_context;
}

TEST(llm_config, test_llm_config) {
    mock("llm_config").expectOneCall("http_request").ignoreOtherParameters();
    mock("llm_config").expectOneCall("new_http_ctx").ignoreOtherParameters();

    aigw_llm_config_t *llm_config = (aigw_llm_config_t *)cpputest_malloc(sizeof(aigw_llm_config_t));
    memset(llm_config, 0, sizeof(aigw_llm_config_t));
    int ret = get_llm_config(basic_ctx, llm_config);

    mock("llm_config").checkExpectations();
    CHECK(ret == 0);
    CHECK(llm_config != NULL);
    aigw_llm_config_destroy(llm_config);
}
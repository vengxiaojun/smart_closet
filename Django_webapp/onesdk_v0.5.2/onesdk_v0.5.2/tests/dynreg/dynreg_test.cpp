#include "CppUTest/TestHarness.h"
#include "CppUTestExt/MockSupport.h"

extern "C"
{
  #include "CppUTest/TestHarness_c.h"
  #include "iot_basic.h"
  #include "iot/dynreg.h"
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

TEST_GROUP(dynreg) {
    iot_basic_ctx_t *device_ctx;  // 改为指针类型

    void setup() {
        // 动态分配内存
        device_ctx = (iot_basic_ctx_t *)cpputest_malloc(sizeof(iot_basic_ctx_t));
        memset(device_ctx, 0, sizeof(iot_basic_ctx_t));
        device_ctx->config = (iot_basic_config_t *)cpputest_malloc(sizeof(iot_basic_config_t));
        memset(device_ctx->config, 0, sizeof(iot_basic_config_t));
        iot_basic_config_t *pconfig = device_ctx->config;
        // 初始化结构体成员
        pconfig->http_host = cpputest_strdup(SAMPLE_HTTP_HOST);
        pconfig->instance_id = cpputest_strdup(SAMPLE_INSTANCE_ID);
        pconfig->product_key =cpputest_strdup(SAMPLE_PRODUCT_KEY);
        pconfig->product_secret =cpputest_strdup(SAMPLE_PRODUCT_SECRET);
        pconfig->device_name =cpputest_strdup(SAMPLE_DEVICE_NAME);
        // device_ctx->device_name = "sdk-llm-config-test";
        // device_ctx->device_secret =cpputest_strdup("98cb52e94e437ee407dbed37"); // P1
        // device_ctx->device_secret = cpputest_strdup("3486b6f47e9216c47b7a6320"); // sdk-test
        pconfig->verify_ssl= false;
        pconfig->auth_type = ONESDK_AUTH_DYNAMIC_NO_PRE_REGISTERED;
    }

    void teardown() {
        onesdk_iot_basic_deinit(device_ctx);

        mock("dynreg").clear();
        mock().clear();
    }
};


http_response_t *http_request(http_request_context_t *http_context) {
    mock("dynreg").actualCall("http_request");
    char *mock_body = "{\"ResponseMetadata\":{\"Action\":\"DynamicRegister\",\"Version\":\"2021-12-14\"},\"Result\":{\"len\":24,\"payload\":\"Kg/hy+SdiBzWE80q3deSlx5PIaPv3OVo6z2rk/nvoiQ=\"}}";
    http_response_t *mock_response = (http_response_t *)cpputest_malloc(sizeof(http_response_t));
    memset(mock_response, 0, sizeof(http_response_t));
    mock_response->body_size = strlen(mock_body)+1;
    mock_response->response_body = cpputest_strdup(mock_body);
    mock_response->error_code = 200;
    http_context->response = mock_response;

    return mock_response;
}

http_request_context_t *new_http_ctx() {
    mock("dynreg").actualCall("new_http_ctx");
    http_request_context_t *http_context = (http_request_context_t *)cpputest_malloc(sizeof(http_request_context_t));
    memset(http_context, 0, sizeof(http_request_context_t));
    return http_context;
}

TEST(dynreg, test_dynreg) {
    mock("dynreg").expectOneCall("http_request");
    mock("dynreg").expectOneCall("new_http_ctx");

    int ret = dynamic_register(device_ctx);
    CHECK(ret == 0);
    STRCMP_EQUAL("98cb52e94e437ee407dbed37", device_ctx->config->device_secret);
    mock("dynreg").checkExpectations();
}
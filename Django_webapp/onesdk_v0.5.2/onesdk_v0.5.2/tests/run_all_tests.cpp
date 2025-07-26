#include "CppUTest/CommandLineTestRunner.h"
#define ENABLE_AI
#define ENABLE_AI_REALTIME

// IMPORT_TEST_GROUP(auth); // onesdk_new_http_ctx leaks
// IMPORT_TEST_GROUP(util); // ok
// IMPORT_TEST_GROUP(iot_basic); // ok
// IMPORT_TEST_GROUP(llm_config); // ok
IMPORT_TEST_GROUP(dynreg);
IMPORT_TEST_GROUP(hardware_id);

int main(int argc, char** argv)
{
    return RUN_ALL_TESTS(argc, argv);
}

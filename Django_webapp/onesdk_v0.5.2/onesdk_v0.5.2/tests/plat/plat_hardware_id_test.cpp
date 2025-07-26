#include "CppUTest/TestHarness.h"
#include "CppUTestExt/MockSupport.h"

extern "C"
{
  #include "CppUTest/TestHarness_c.h"
  #include "plat/platform.h"
}


TEST_GROUP(hardware_id) {
    void setup() {
    }

    void teardown() {
    }
};



TEST(hardware_id, test_hardware_id) {
    char *hw_id = plat_hardware_id();
    char *f1 = fallback_mac_addr();
    char *f2 = fallback_mac_addr();

    STRCMP_EQUAL(f1, f2);
    CHECK(hw_id != NULL);

    cpputest_free(hw_id);
    cpputest_free(f1);
    cpputest_free(f2);
}
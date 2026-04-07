#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/fs.h>
#include <linux/rockchip/rockchip_sip.h>
#include <linux/io.h>

#define HDMI_RX              6
#define HDCP_FUNC_STORAGE_INCRYPT 1
#define HDCP_FUNC_KEY_LOAD   2
#define HDCP_FUNC_ENCRYPT_MODE 3
#define VENDOR_DATA_SIZE     330

static char *keyfile = "/home/radxa/hdcp_struct_308.bin";
module_param(keyfile, charp, 0444);

static int __init vendor_fix_init(void)
{
    struct file *f;
    uint8_t hdcp_data[VENDOR_DATA_SIZE];
    void __iomem *base;
    struct arm_smccc_res res;
    loff_t pos = 0;
    ssize_t size;

    pr_info("vendor_fix: Loading key from %s\n", keyfile);

    f = filp_open(keyfile, O_RDONLY, 0);
    if (IS_ERR(f)) return PTR_ERR(f);
    
    memset(hdcp_data, 0, sizeof(hdcp_data));
    size = kernel_read(f, hdcp_data, VENDOR_DATA_SIZE, &pos);
    filp_close(f, NULL);
    
    if (size < 0) return size;
    pr_info("vendor_fix: Read %zd bytes, first 8: %*ph\n", size, 8, hdcp_data);

    base = sip_hdcp_request_share_memory(HDMI_RX);
    if (!base) return -ENOMEM;

    memcpy_toio(base, hdcp_data, size);
    
    /* Try all SIP function combinations */
    pr_info("vendor_fix: === Trying all SIP combinations ===\n");
    
    res = sip_hdcp_config(HDCP_FUNC_STORAGE_INCRYPT, HDMI_RX, 0);
    pr_info("vendor_fix: STORAGE_INCRYPT(1, RX, 0) = a0:0x%lx\n", res.a0);
    
    res = sip_hdcp_config(HDCP_FUNC_STORAGE_INCRYPT, HDMI_RX, 1);
    pr_info("vendor_fix: STORAGE_INCRYPT(1, RX, 1) = a0:0x%lx\n", res.a0);

    res = sip_hdcp_config(HDCP_FUNC_KEY_LOAD, HDMI_RX, 0);
    pr_info("vendor_fix: KEY_LOAD(2, RX, 0) = a0:0x%lx\n", res.a0);

    res = sip_hdcp_config(HDCP_FUNC_KEY_LOAD, HDMI_RX, 1);
    pr_info("vendor_fix: KEY_LOAD(2, RX, 1) = a0:0x%lx\n", res.a0);

    res = sip_hdcp_config(HDCP_FUNC_ENCRYPT_MODE, HDMI_RX, 0);
    pr_info("vendor_fix: ENCRYPT_MODE(3, RX, 0) = a0:0x%lx\n", res.a0);

    res = sip_hdcp_config(HDCP_FUNC_ENCRYPT_MODE, HDMI_RX, 1);
    pr_info("vendor_fix: ENCRYPT_MODE(3, RX, 1) = a0:0x%lx\n", res.a0);

    return 0;
}

static void __exit vendor_fix_exit(void) { pr_info("vendor_fix: unloaded\n"); }

module_init(vendor_fix_init);
module_exit(vendor_fix_exit);
MODULE_LICENSE("GPL");

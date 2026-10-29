// SPDX-License-Identifier: GPL-2.0-only
/*
 * Bring-up only, not for upstream: the Pixel 9a's RT9470 (run by Google's
 * rt9471 driver) as an OTG boost only, a regulator on its OTG_EN bit
 * (FUNCTION 0x02 bit 1), which the MAX77779 charger enables to give a USB-C
 * device VBUS. Probe reads the device id and turns off JEITA (0x0C bit 7)
 * and the I2C watchdog (TOP 0x01 bits 1:0): with either on, VBUS collapsed
 * under the boost. With the watchdog off, nothing turns the boost off after
 * a crash. The charger part of the chip (charging, BC1.2, its interrupts)
 * is left alone.
 *
 * Registers from mainline rt9471.c and Google's GPL rt9471_charger.h
 * (google-modules/bms at 183509aff980).
 */

#include <linux/bitfield.h>
#include <linux/i2c.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/regmap.h>
#include <linux/regulator/driver.h>
#include <linux/regulator/of_regulator.h>

#define RT9471_REG_OTGCFG	0x00
#define RT9471_REG_TOP		0x01
#define  RT9471_WDT		GENMASK(1, 0)
#define RT9471_REG_FUNC		0x02
#define  RT9471_OTGEN		BIT(1)
#define RT9471_REG_INFO		0x0b
#define RT9471_REG_JEITA	0x0c
#define  RT9471_JEITA_EN	BIT(7)
#define  RT9471_DEVID		GENMASK(6, 3)

static bool rt9471_boost_writeable(struct device *dev, unsigned int reg)
{
	return reg == RT9471_REG_FUNC || reg == RT9471_REG_TOP ||
	       reg == RT9471_REG_JEITA;
}

static const struct regmap_config rt9471_boost_regmap = {
	.reg_bits = 8,
	.val_bits = 8,
	.max_register = 0x12,
	.writeable_reg = rt9471_boost_writeable,
	.cache_type = REGCACHE_NONE,
};

static const struct regulator_ops rt9471_boost_ops = {
	.enable = regulator_enable_regmap,
	.disable = regulator_disable_regmap,
	.is_enabled = regulator_is_enabled_regmap,
};

static const struct regulator_desc rt9471_boost_desc = {
	.name = "rt9471-otg-boost",
	.type = REGULATOR_VOLTAGE,
	.owner = THIS_MODULE,
	.ops = &rt9471_boost_ops,
	.fixed_uV = 5000000,
	.n_voltages = 1,
	.enable_reg = RT9471_REG_FUNC,
	.enable_mask = RT9471_OTGEN,
	.enable_time = 5000,
};

static int rt9471_boost_probe(struct i2c_client *client)
{
	struct device *dev = &client->dev;
	struct regulator_config cfg = {};
	struct regulator_dev *rdev;
	struct regmap *map;
	unsigned int info;
	int ret;

	map = devm_regmap_init_i2c(client, &rt9471_boost_regmap);
	if (IS_ERR(map))
		return PTR_ERR(map);

	ret = regmap_read(map, RT9471_REG_INFO, &info);
	if (ret)
		return dev_err_probe(dev, ret, "no answer\n");
	/* RT9470 0x9, RT9470D 0xa, RT9471 0xd, RT9471D 0xe */
	switch (FIELD_GET(RT9471_DEVID, info)) {
	case 0x9: case 0xa: case 0xd: case 0xe:
		break;
	default:
		return dev_err_probe(dev, -ENODEV, "unknown id %#x\n", info);
	}
	dev_info(dev, "id %#lx\n", FIELD_GET(RT9471_DEVID, info));

	ret = regmap_update_bits(map, RT9471_REG_JEITA, RT9471_JEITA_EN, 0) ?:
	      regmap_update_bits(map, RT9471_REG_TOP, RT9471_WDT, 0);
	if (ret)
		return dev_err_probe(dev, ret, "cannot turn off JEITA and the watchdog\n");

	cfg.dev = dev;
	cfg.regmap = map;
	cfg.of_node = dev->of_node;
	cfg.init_data = of_get_regulator_init_data(dev, dev->of_node,
						   &rt9471_boost_desc);
	rdev = devm_regulator_register(dev, &rt9471_boost_desc, &cfg);
	return PTR_ERR_OR_ZERO(rdev);
}

static const struct of_device_id rt9471_boost_of_match[] = {
	{ .compatible = "omamobile,tegu-rt9471-boost" },
	{ }
};
MODULE_DEVICE_TABLE(of, rt9471_boost_of_match);

static struct i2c_driver rt9471_boost_driver = {
	.driver = {
		.name = "tegu-rt9471-boost",
		.of_match_table = rt9471_boost_of_match,
	},
	.probe = rt9471_boost_probe,
};
module_i2c_driver(rt9471_boost_driver);

MODULE_DESCRIPTION("RT9471 OTG boost for the Pixel 9a's USB-C port");
MODULE_LICENSE("GPL");

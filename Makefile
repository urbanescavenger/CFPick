# Author: mingxiaoyu (fengying0347@163.com)
#
# Licensed to the public under the GNU General Public License v3.
#

include $(TOPDIR)/rules.mk

PKG_NAME:=luci-app-passwall-speedtest

LUCI_TITLE:=LuCI support for PassWall-based Cloudflare IP speed test
# The standalone engine (cf-speedtest) is a stdlib-only Python program; these
# are the OpenWrt sub-packages that provide the modules it imports.
LUCI_DEPENDS:=+curl +ca-bundle +python3-light +python3-urllib +python3-codecs +python3-openssl +python3-email
LUCI_PKGARCH:=all
PKG_VERSION:=2.1
PKG_RELEASE:=0
PKG_LICENSE:=AGPL-3.0
PKG_MAINTAINER:=<https://github.com/urbanescavenger/luci-app-passwall-speedtest>

define Package/$(PKG_NAME)/conffiles
/etc/config/passwall-speedtest
endef

# The standalone engine is maintained once in debian/ (the Debian/Ubuntu
# implementation) and copied into the package tree at build time; nothing is
# duplicated in git.  These hooks MUST be defined before including luci.mk:
# BuildPackage expands `$(call Build/Prepare/$(LUCI_NAME))` while luci.mk is
# being included, so a hook defined after it is silently ignored (the package
# then builds without /usr/lib/cf-speedtest).
define StandaloneEnginePrepare
	$(INSTALL_DIR) $(PKG_BUILD_DIR)/root/usr/lib/cf-speedtest
	$(CP) -R $(CURDIR)/debian/cfspeedtest $(PKG_BUILD_DIR)/root/usr/lib/cf-speedtest/
	# No web/ assets: the OpenWrt app uses the operations console for its UI.
	$(CP) -R $(CURDIR)/debian/data $(PKG_BUILD_DIR)/root/usr/lib/cf-speedtest/
endef

define Build/Prepare/luci-app-passwall-speedtest
$(StandaloneEnginePrepare)
endef

# Also support building the git checkout directly (directory name is the
# repository name, not the package name).
define Build/Prepare/$(notdir $(CURDIR))
$(StandaloneEnginePrepare)
endef

include $(TOPDIR)/feeds/luci/luci.mk

# call BuildPackage - OpenWrt buildroot signature

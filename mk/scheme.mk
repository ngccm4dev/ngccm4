define family_tag
$(patsubst crypto_%,%,$(1))
endef

define family_of_impl
$(word 1,$(subst /, ,$(1)))
endef

define scheme_of_impl
$(word 2,$(subst /, ,$(1)))
endef

define implementation_of_impl
$(word 3,$(subst /, ,$(1)))
endef

define family_entry
$(strip $(ENTRY_$(call family_tag,$(1))))
endef

define family_app_sources
$(strip $(APP_SRCS_$(call family_tag,$(1))))
endef

define family_available_apps
$(basename $(notdir $(call family_app_sources,$(1))))
endef

IMPLS := $(sort $(foreach family,$(SUPPORTED_FAMILIES),$(patsubst %/,%,$(dir $(wildcard $(family)/*/*/$(call family_entry,$(family)))))))
ALL_IMPLS := $(IMPLS)

# Skip list: mk/skip.mk (SKIP_SCHEMES, SKIP_IMPLS) plus SKIP="..." from the
# command line; NOSKIP=1 disables it. See mk/skip.mk for the syntax.
SKIP_MK ?= mk/skip.mk
-include $(SKIP_MK)
SKIP ?=
NOSKIP ?= 0
SKIP_SCHEMES += $(foreach s,$(SKIP),$(if $(findstring /,$(s)),,$(s)))
SKIP_IMPLS += $(foreach s,$(SKIP),$(if $(findstring /,$(s)),$(s),))
SKIP_SCHEMES := $(sort $(strip $(SKIP_SCHEMES)))
SKIP_IMPLS := $(sort $(strip $(SKIP_IMPLS)))
SKIPPED_IMPLS := $(sort $(filter $(SKIP_IMPLS),$(IMPLS)) \
	$(foreach impl,$(IMPLS),$(if $(filter $(SKIP_SCHEMES),$(call scheme_of_impl,$(impl))),$(impl))))
ifneq ($(NOSKIP),1)
IMPLS := $(filter-out $(SKIPPED_IMPLS),$(IMPLS))
else
SKIPPED_IMPLS :=
endif

ifneq ($(strip $(FAMILY)),)
IMPLS := $(filter $(FAMILY)/%,$(IMPLS))
endif

ifneq ($(strip $(SCHEME)),)
IMPLS := $(foreach impl,$(IMPLS),$(if $(filter $(SCHEME),$(call scheme_of_impl,$(impl))),$(impl)))
endif

ifneq ($(strip $(IMPLEMENTATION)),)
IMPLS := $(foreach impl,$(IMPLS),$(if $(filter $(IMPLEMENTATION),$(call implementation_of_impl,$(impl))),$(impl)))
endif

SCHEMES := $(patsubst %/,%,$(IMPLS))
SUPPORTED_APPS := $(sort $(foreach family,$(SUPPORTED_FAMILIES),$(call family_available_apps,$(family))))

define dkex_sig_mldsa_impl
$(wildcard $(1)/dkex_sig_mldsa.c)
endef

DKEX_SIG_MLDSA_IMPLS := $(foreach impl,$(IMPLS),$(if $(call dkex_sig_mldsa_impl,$(impl)),$(impl)))
DKEX_SIG_MLDSA_SRCS := $(sort $(wildcard crypto_sign/dilithium/ref/*.c))

ifneq ($(strip $(DKEX_SIG_MLDSA_IMPLS)),)
ifeq ($(filter $(DKEX_SIG_MLDSA_LEVEL),2 3 5),)
$(error Unsupported DKEX_SIG_MLDSA_LEVEL '$(DKEX_SIG_MLDSA_LEVEL)'; use 2, 3, or 5)
endif
endif

DKEX_SIG_MLDSA_BUILD_CONFIG := $(if $(strip $(DKEX_SIG_MLDSA_IMPLS)),DKEX_SIG_MLDSA_LEVEL=$(DKEX_SIG_MLDSA_LEVEL))

ifneq ($(strip $(APP)),)
ifneq ($(strip $(FAMILY)),)
ifeq ($(filter $(APP),$(call family_available_apps,$(FAMILY))),)
$(error Unsupported APP '$(APP)' for FAMILY '$(FAMILY)'; available apps: $(call family_available_apps,$(FAMILY)))
endif
else
ifeq ($(filter $(APP),$(SUPPORTED_APPS)),)
$(error Unsupported APP '$(APP)'; available apps: $(SUPPORTED_APPS))
endif
endif
endif

define impl_name
$(subst /,_,$(1))
endef

# Optional per-implementation configuration (crypto_<fam>/<scheme>/<impl>/config.mk
# and mk/<family>_<scheme>_<impl>.mk). They may define:
#   IMPL_CFLAGS_<impl_name>         extra compiler flags for the implementation sources
#   IMPL_EXCLUDE_COMMON_<impl_name> common/ sources to leave out of the archive
#   IMPL_EXCLUDE_SRC_<impl_name>    implementation sources (full relative paths) to leave out
#   IMPL_DEPS_<impl_name>           other implementations linked into this one (see below)
#   IMPL_DEP_KEEP_<impl_name>       exported symbol patterns of those dependencies
# They are included here, before any rule is generated, so that the variables
# are visible when define_impl is expanded.
-include $(foreach impl,$(ALL_IMPLS),$(impl)/config.mk) $(foreach impl,$(ALL_IMPLS),mk/$(call impl_name,$(impl)).mk)

# Implementation dependencies (IMPL_DEPS_<impl_name> in config.mk): other
# implementations of this tree, e.g. crypto_kem/POLARLAC-128/ref, whose sources
# are compiled as usual, partially linked into one relocatable object per
# dependency and reduced to their public API (IMPL_DEP_KEEP_<impl_name>,
# default kem_* sig_* pke_* kex_*) with objcopy, so that two dependencies with
# the same internal symbol names (poly_*, shake128, ...) can be linked into one
# protocol implementation. Dependencies are built even when they are not part
# of the current selection.
define impl_deps
$(strip $(IMPL_DEPS_$(call impl_name,$(1))))
endef
DEP_IMPLS := $(sort $(foreach impl,$(IMPLS),$(call impl_deps,$(impl))))
MISSING_DEPS := $(filter-out $(ALL_IMPLS),$(DEP_IMPLS))
ifneq ($(strip $(MISSING_DEPS)),)
$(error IMPL_DEPS refer to implementations that do not exist: $(MISSING_DEPS))
endif
BUILD_IMPLS := $(sort $(IMPLS) $(DEP_IMPLS))
DEFAULT_DEP_KEEP := kem_* sig_* pke_* PKE_* kex_*

define available_apps_for_impl
$(call family_available_apps,$(call family_of_impl,$(1)))
endef

define selected_apps_for_impl
$(if $(strip $(APP)),$(filter $(APP),$(call available_apps_for_impl,$(1))),$(call available_apps_for_impl,$(1)))
endef

define impl_sources
$(filter-out $(IMPL_EXCLUDE_SRC_$(call impl_name,$(1))),$(wildcard $(1)/*.c) $(wildcard $(1)/*.s) $(wildcard $(1)/*.S))
endef

define impl_lib_sources
$(filter-out $(IMPL_EXCLUDE_COMMON_$(call impl_name,$(1))),$(filter %.c %.s %.S,$(COMMON_LIB_SRCS))) \
$(filter %.c %.s %.S,$(PLATFORM_LIB_SRCS)) \
$(call impl_sources,$(1))
endef

# ML-DSA level of a DKEX implementation. The submission's build.sh compiles
# DKEX-128 with level 2 (ML-DSA-44) and DKEX-256/DKEX-512 with level 5
# (ML-DSA-87); the official KAT vectors depend on this. A DKEX_SIG_MLDSA_LEVEL
# given on the make command line or in the environment overrides it for every
# instance (the mk/config.mk default only documents the fallback).
define dkex_mldsa_level
$(if $(filter-out file default undefined,$(origin DKEX_SIG_MLDSA_LEVEL)),$(DKEX_SIG_MLDSA_LEVEL),$(if $(findstring -128/,$(1)/),2,5))
endef

define impl_cppflags
$(if $(call dkex_sig_mldsa_impl,$(1)),-DDKEX_SIG_BACKEND_MLDSA -DDKEX_SIG_MLDSA_LEVEL=$(call dkex_mldsa_level,$(1)) -DDILITHIUM_MODE=$(call dkex_mldsa_level,$(1)))
endef

# Flags that only apply to the implementation's own C sources and to the app
# driver: the generated ngcc_config.h (force-included) and IMPL_CFLAGS_<impl>.
define impl_c_cppflags
$(if $(wildcard $(1)/ngcc_config.h),-include $(CURDIR)/$(1)/ngcc_config.h) $(IMPL_CFLAGS_$(call impl_name,$(1)))
endef

define src_cppflags
$(if $(filter %.c,$(2)),$(if $(filter $(1)/%,$(2)),$(call impl_c_cppflags,$(1))))
endef

define include_flags_for_impl
-I$(CURDIR)/common \
-I$(CURDIR)/$(1) \
$(foreach dir,$(PLATFORM_INCLUDE_DIRS),-I$(CURDIR)/$(dir))
endef

define dkex_sig_mldsa_source
$(if $(call dkex_sig_mldsa_impl,$(1)),$(filter $(1)/dkex_sig_mldsa.c $(1)/randombytes.c,$(2)))
endef

define source_include_flags_for_impl
$(if $(call dkex_sig_mldsa_source,$(1),$(2)),-I$(CURDIR)/crypto_sign/dilithium/ref) $(call include_flags_for_impl,$(1))
endef

define profile_dir
$(if $(filter hashprof,$(1)),hashprof/,)
endef

define obj_from_src
obj/$(call profile_dir,$(2))$(call impl_name,$(1))/$(patsubst %.c,%.o,$(patsubst %.S,%.o,$(patsubst %.s,%.o,$(3))))
endef

define lib_objects
$(foreach src,$(call impl_lib_sources,$(1)),$(call obj_from_src,$(1),$(2),$(src)))
endef

# Objects of an implementation's own sources only (no common/ or platform code).
define impl_own_objects
$(foreach src,$(call impl_sources,$(1)),$(call obj_from_src,$(1),$(2),$(src)))
endef

# $(1)=implementation, $(2)=profile, $(3)=dependency implementation
define dep_object
obj/$(call profile_dir,$(2))$(call impl_name,$(1))/deps/$(call impl_name,$(3)).o
endef

define dep_objects
$(foreach dep,$(call impl_deps,$(1)),$(call dep_object,$(1),$(2),$(dep)))
endef

define dep_keep_flags
$(foreach sym,$(or $(strip $(IMPL_DEP_KEEP_$(call impl_name,$(1)))),$(DEFAULT_DEP_KEEP)),-G '$(sym)')
endef

define app_source
$(call family_of_impl,$(1))/$(2).c
endef

define app_object
$(call obj_from_src,$(1),normal,$(call app_source,$(1),$(2)))
endef

define lib_target
obj/$(call profile_dir,$(2))lib$(call impl_name,$(1)).a
endef

define mldsa_obj_from_src
obj/$(call impl_name,$(1))_mldsa/$(patsubst %.c,%.o,$(2))
endef

define mldsa_lib_objects
$(foreach src,$(DKEX_SIG_MLDSA_SRCS),$(call mldsa_obj_from_src,$(1),$(src)))
endef

define mldsa_lib_target
$(if $(call dkex_sig_mldsa_impl,$(1)),obj/lib$(call impl_name,$(1))_mldsa.a)
endef

define elf_target
elf/$(call impl_name,$(1))_$(2).elf
endef

define bin_target
bin/$(call impl_name,$(1))_$(2).bin
endef

define elf_library
$(call lib_target,$(1),$(if $(filter hashing,$(2)),hashprof,normal))
endef

define elf_libraries
$(call elf_library,$(1),$(2)) $(call mldsa_lib_target,$(1))
endef

define elf_dep_objects
$(call dep_objects,$(1),$(if $(filter hashing,$(2)),hashprof,normal))
endef

define lib_cppflags
$(if $(filter hashprof,$(2)),-DHASHING_PROFILE)
endef

# The hashing app counts the assembly hash primitives whoever calls them: the
# hashprof object (common/hashprof.c) supplies __wrap_ trampolines and the ELF
# is linked with --wrap for the two primitives. $(1)=implementation, $(2)=app.
HASHPROF_WRAP_LDFLAGS := -Wl,--wrap=KeccakF1600_StatePermute -Wl,--wrap=KeccakF1600_StatePermute_plain -Wl,--wrap=sm3_bit_compress_asm
define hashing_link_extras
$(if $(and $(filter hashing,$(2)),$(filter common/hashprof.c,$(call impl_lib_sources,$(1)))),$(call obj_from_src,$(1),hashprof,common/hashprof.c) $(HASHPROF_WRAP_LDFLAGS))
endef

ELFS := $(foreach impl,$(IMPLS),$(foreach app,$(call selected_apps_for_impl,$(impl)),$(call elf_target,$(impl),$(app))))
BINS := $(ELFS:elf/%.elf=bin/%.bin)

define define_impl
$(call lib_target,$(1),normal): $(call lib_objects,$(1),normal)
	@printf '  AR      $$@\n'
	$(Q)mkdir -p $$(@D)
	$(Q)rm -f $$@
	$(Q)$(AR) rcs $$@ $$^

$(call lib_target,$(1),hashprof): $(call lib_objects,$(1),hashprof)
	@printf '  AR      $$@\n'
	$(Q)mkdir -p $$(@D)
	$(Q)rm -f $$@
	$(Q)$(AR) rcs $$@ $$^

$(if $(call dkex_sig_mldsa_impl,$(1)),$(eval $(call mldsa_lib_target,$(1)): $(call mldsa_lib_objects,$(1)) ; @printf '  AR      $$@\n'; $(Q)mkdir -p $$(@D); $(Q)$(AR) rcs $$@ $$^))

$(foreach src,$(DKEX_SIG_MLDSA_SRCS),$(if $(call dkex_sig_mldsa_impl,$(1)),$(eval $(call mldsa_obj_from_src,$(1),$(src)): $(src) $(COMPILEDEPS) | platform-sync ; @printf '  CC      $(src) [mldsa]\n'; $(Q)mkdir -p $$(@D); $(Q)$(CC) $(CPPFLAGS) $(call impl_cppflags,$(1)) $(CFLAGS) -I$(CURDIR)/common -I$(CURDIR)/crypto_sign/dilithium/ref -c $(src) -o $$@)))

$(foreach src,$(call impl_lib_sources,$(1)),$(eval $(call obj_from_src,$(1),normal,$(src)): $(src) $(COMPILEDEPS) | platform-sync ; @printf '  $(if $(filter %.c,$(src)),CC,AS)      $(src)\n'; $(Q)mkdir -p $$(@D); $(Q)$(CC) $(CPPFLAGS) $(call impl_cppflags,$(1)) $(CFLAGS) $(call src_cppflags,$(1),$(src)) $(call source_include_flags_for_impl,$(1),$(src)) -c $(src) -o $$@))
$(foreach src,$(call impl_lib_sources,$(1)),$(eval $(call obj_from_src,$(1),hashprof,$(src)): $(src) $(COMPILEDEPS) | platform-sync ; @printf '  $(if $(filter %.c,$(src)),CC,AS)      $(src) [hashprof]\n'; $(Q)mkdir -p $$(@D); $(Q)$(CC) $(CPPFLAGS) $(call lib_cppflags,$(1),hashprof) $(call impl_cppflags,$(1)) $(CFLAGS) $(call src_cppflags,$(1),$(src)) $(call source_include_flags_for_impl,$(1),$(src)) -c $(src) -o $$@))

$(foreach app,$(call selected_apps_for_impl,$(1)),$(eval $(call app_object,$(1),$(app)): $(call app_source,$(1),$(app)) $(COMPILEDEPS) | platform-sync ; @printf '  CC      $(call app_source,$(1),$(app))\n'; $(Q)mkdir -p $$(@D); $(Q)$(CC) $(CPPFLAGS) $(call impl_cppflags,$(1)) $(CFLAGS) $(call impl_c_cppflags,$(1)) $(call include_flags_for_impl,$(1)) -c $(call app_source,$(1),$(app)) -o $$@))

$(foreach dep,$(call impl_deps,$(1)),$(foreach prof,normal hashprof,$(eval $(call dep_object,$(1),$(prof),$(dep)): $(call impl_own_objects,$(dep),$(prof)) $(wildcard $(1)/config.mk) | platform-sync ; @printf '  DEP     $(dep) -> $$@\n'; $(Q)mkdir -p $$(@D); $(Q)$(CROSS_PREFIX)-ld -r -o $$@.tmp $$(filter %.o,$$^); $(Q)$(OBJCOPY) -w $(call dep_keep_flags,$(1)) $$@.tmp $$@; $(Q)rm -f $$@.tmp)))

$(foreach app,$(call selected_apps_for_impl,$(1)),$(eval $(call elf_target,$(1),$(app)): $(call app_object,$(1),$(app)) $(call elf_dep_objects,$(1),$(app)) $(call elf_libraries,$(1),$(app)) $(LIBDEPS) $(LDSCRIPT) | platform-sync))
$(foreach app,$(call selected_apps_for_impl,$(1)),$(eval $(call elf_target,$(1),$(app)):
	@printf '  LD      $$@\n'
	$(Q)mkdir -p $$(@D)
	$(Q)$(LD) $(CFLAGS) $(call app_object,$(1),$(app)) $(call elf_dep_objects,$(1),$(app)) $(call hashing_link_extras,$(1),$(app)) $(LDFLAGS) -Wl,--start-group $(call elf_libraries,$(1),$(app)) $(LDLIBS) -Wl,--end-group -o $$@
	@printf '  SIZE    $$@\n'
	$(Q)$(SIZE) $$@))

$(foreach app,$(call selected_apps_for_impl,$(1)),$(eval $(call bin_target,$(1),$(app)): $(call elf_target,$(1),$(app))
	@printf '  OBJCOPY $$@\n'
	$(Q)mkdir -p $$(@D)
	$(Q)$(OBJCOPY) -Obinary $$< $$@))

endef

$(foreach impl,$(BUILD_IMPLS),$(eval $(call define_impl,$(impl))))

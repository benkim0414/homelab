# Hermes browser seccomp profile

`hermes-browser-amd64.json` is an OCI seccomp profile for the non-root, capability-free
browser on the amd64 `k3s-05` worker. It is not a cluster default. Install it with
[`browser-seccomp.yml`](../browser-seccomp.yml) before deploying
[`hermes/browser.yaml`](../../hermes/browser.yaml).

Source: [Playwright v1.64.1 profile](https://raw.githubusercontent.com/microsoft/playwright/v1.64.1/utils/docker/seccomp_profile.json),
SHA256 `cc3e61cabda6bbc1e53e54d27ba4d55a9d3be829b6dd1a596f4a7b31b1cc7849`.
The upstream profile is based on Docker's default policy with `clone`, `setns`
and `unshare` allowed for Chromium's namespace sandbox. Upstream Playwright is
Apache-2.0 licensed; see its [license](https://github.com/microsoft/playwright/blob/v1.64.1/LICENSE).

Adaptation for Kubernetes/containerd, Linux 6.12 and a pod with no capabilities:

- Convert Docker `archMap` to OCI `architectures` for x86_64 and its compatibility
  ABIs. The Deployment also selects amd64; do not apply this profile on ARM.
- Resolve Docker-only `includes` and `excludes` conditions for amd64 with no
  capabilities. Omit every capability-dependent allow rule and other-architecture
  rules. Keep the `ptrace` rule conditional on kernel >= 4.8 in the reference,
  because the target is kernel 6.12. The resulting profile contains no unresolved
  Docker conditions that containerd could silently ignore.
- Keep `defaultAction: SCMP_ACT_ERRNO` with EPERM. Permit the reference's
  namespace operations so Chromium can apply its own sandbox. This expands
  kernel exposure relative to RuntimeDefault; pod user namespaces are an
  additional boundary, not a replacement for kernel patching.
- Return ENOSYS for `clone3` so libc can fall back to `clone`.
- Permit `chroot` for Chromium to drop filesystem access inside its newly created
  user namespace. The pod retains zero capabilities in its outer namespace;
  allowing the syscall does not grant `CAP_SYS_CHROOT` there. Omitting this rule
  prevented the sandboxed zygote handshake during live testing.
- Permit `rseq`, `close_range`, `faccessat2`, `epoll_pwait2` and `fchmodat2` for
  modern libc/runtime compatibility. No mount, module, BPF, reboot or
  `open_by_handle_at` capability-based allow rules are introduced.

Review the complete JSON after source updates. Test actual launch, public HTTPS
browsing and Chromium renderer namespaces/seccomp; a valid JSON file or successful
pod creation does not establish sandbox operation. Run the Ansible playbook a
second time to check idempotence. A node rebuild must reinstall the profile.
Profile changes affect new containers; recreate the browser pod to test them.
No K3s restart is needed. Stop dependent browser pods before removing the file.

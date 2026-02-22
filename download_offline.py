import os
import urllib.request

REPOS = [
    "https://downloads.openwrt.org/releases/23.05.4/targets/ipq40xx/chromium/packages/",
    "https://downloads.openwrt.org/releases/23.05.4/packages/arm_cortex-a7_neon-vfpv4/base/",
    "https://downloads.openwrt.org/releases/23.05.4/packages/arm_cortex-a7_neon-vfpv4/packages/",
    "https://downloads.openwrt.org/releases/23.05.4/packages/arm_cortex-a7_neon-vfpv4/luci/",
    "https://downloads.openwrt.org/releases/23.05.4/packages/arm_cortex-a7_neon-vfpv4/routing/"
]

PKGS_TO_INSTALL = ["python3-light", "python3-urllib", "python3-logging", "python3-openssl"]
DOWNLOAD_DIR = "offline_pkgs"

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# 1. Fetch metadata
packages_db = {}
for repo in REPOS:
    url = repo + "Packages"
    print(f"Fetching {url}")
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as response:
            data = response.read().decode('utf-8')
            
        current_pkg = {}
        for line in data.splitlines():
            if not line.strip():
                if 'Package' in current_pkg:
                    current_pkg['Repo'] = repo
                    packages_db[current_pkg['Package']] = current_pkg
                current_pkg = {}
            elif ": " in line:
                key, val = line.split(": ", 1)
                current_pkg[key] = val
    except Exception as e:
        print(f"Failed to fetch {repo}: {e}")

# 2. Resolve Dependencies
def get_deps(pkg_name, resolved=None):
    if resolved is None:
        resolved = set()
    if pkg_name in resolved:
        return resolved
    
    # Check if package is available
    if pkg_name not in packages_db:
        print(f"WARNING: Dependency {pkg_name} not found in repos, skipping.")
        return resolved

    resolved.add(pkg_name)
    deps_raw = packages_db[pkg_name].get('Depends', "")
    if deps_raw:
        # e.g., "libc, librt, libffi"
        # can also be python3-base (= 3.10.13-1)
        deps = [d.split('(')[0].strip() for d in deps_raw.split(',')]
        for d in deps:
            get_deps(d, resolved)
    
    return resolved

all_required = set()
for p in PKGS_TO_INSTALL:
    all_required.update(get_deps(p))

print(f"Total packages to download: {len(all_required)}")

# 3. Download
for pkg_name in sorted(list(all_required)):
    pkg = packages_db[pkg_name]
    repo = pkg['Repo']
    filename = pkg['Filename']
    url = repo + filename
    local_path = os.path.join(DOWNLOAD_DIR, os.path.basename(filename))
    
    if os.path.exists(local_path):
        print(f"Already downloaded {filename}")
        continue

    print(f"Downloading {filename}...")
    try:
        urllib.request.urlretrieve(url, local_path)
    except Exception as e:
        print(f"Failed to download {filename}: {e}")

print("✅ Finished downloading offline dependencies.")

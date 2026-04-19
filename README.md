# Alya

This repository contains a curated collection of infrastructure automation scripts.

Primary blueprint:

- PowerShell and shell-driven operations for day-to-day administration
- Focus on practical runbooks and operator-friendly execution

Also included:

- Targeted Python automation where API-centric workflows are a better fit

Current areas covered:

- **Active Directory Domain Services (AD DS)** administration and automation
- **VMware vSphere** environment management using **PowerCLI**
- **Windows Native** services and system management (PowerShell/batch)
- **Nutanix Prism / AHV** validation automation and SOP guidance

These scripts are crafted for system administrators and DevOps professionals aiming to streamline infrastructure operations across on-premises Windows Server domains, VMware environments, Nutanix Cloud Platform environments, and native Windows systems.

---

## 📬 Author

**Name:** Areen Agrawal
**Email:** asyoulikeit747@gmail.com

---

## 📄 License

**Unlicensed** – This repository is released without a license.  
You are free to use the code, but no warranties or guarantees are provided.

---

## 📁 Repository Structure

```
/alya
├── ad-ds/             # Scripts related to Active Directory Domain Services
├── nutanix-prism/     # Nutanix Prism/AHV validation toolkit (Python + docs)
├── vmware-powercli/   # Scripts for managing VMware vSphere environments via PowerCLI
├── windows-native/    # PowerShell scripts and batch files for managing native Windows services, scheduled tasks, etc.
└── README.md          # Project overview and usage instructions
```

## Script Runtimes

- **PowerShell**: Primary runtime across AD DS, VMware, and Windows-native operations.
- **Shell/CLI workflows**: Used where direct command-line execution is the natural operator path.
- **Python**: Used in `nutanix-prism/` for API-driven Nutanix AHV/Prism automation.

---

## 🛠️ Prerequisites

### ✅ PowerShell
Make sure PowerShell 5.1+ or PowerShell Core (7+) is installed.

### ✅ Modules Required
- For AD DS scripts:
  - `ActiveDirectory` module (Install via RSAT or `Install-WindowsFeature RSAT-AD-PowerShell`)
- For VMware scripts:
  - [VMware PowerCLI](https://developer.vmware.com/powercli)

    Install using:
    ```powershell
    Install-Module -Name VMware.PowerCLI -Scope CurrentUser
    ```
- For Windows Native scripts:
  - Built-in Windows PowerShell modules (ScheduledTasks, etc.)

### ✅ Python (for Nutanix Prism tooling)

- Python 3.9+
- `pip` package manager

Install dependencies for Nutanix scripts:

```bash
pip install -r nutanix-prism/requirements.txt
```

---

## 🚀 How to Use

1. Clone the repository:
   ```bash/cmd
   git clone https://github.com/veg-salad/alya.git
   cd alya
   ```

2. Go to the area you want to use (`ad-ds`, `vmware-powercli`, `windows-native`, or `nutanix-prism`) and follow folder-specific documentation.

3. For Nutanix Prism Python tooling, install dependencies first:
  ```bash
  pip install -r nutanix-prism/requirements.txt
  ```

---
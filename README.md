# Alya

This repository contains a curated collection of PowerShell scripts and batch files designed for:

- **Active Directory Domain Services (AD DS)** administration and automation
- **VMware vSphere** environment management using **PowerCLI**
- **Windows Native** services and system management

These scripts are crafted for system administrators and DevOps professionals aiming to streamline infrastructure operations across on-premises Windows Server domains, VMware environments, and native Windows systems.

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
├── vmware-powercli/   # Scripts for managing VMware vSphere environments via PowerCLI
├── windows-native/    # PowerShell scripts and batch files for managing native Windows services, scheduled tasks, etc.
└── README.md          # Project overview and usage instructions
```
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

---

## 🚀 How to Use

1. Clone the repository:
   ```bash/cmd
   git clone https://github.com/veg-salad/alya.git
   cd alya
   ```

---
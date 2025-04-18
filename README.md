# Alya

This repository contains a curated collection of PowerShell scripts designed for:

- **Active Directory Domain Services (AD DS)** administration and automation
- **VMware vSphere** environment management using **PowerCLI**

These scripts are crafted for system administrators and DevOps professionals aiming to streamline infrastructure operations across on-premises Windows Server domains and VMware environments.

---

## 📬 Author

**Name:** Stefan Salvatore
**Email:** whattheheck.stefan@gmail.com

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
├── .gitignore         # Git ignore rules for excluding files/directories
├── CHANGELOG.md       # Log of all notable changes and version history
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

---

## 🚀 How to Use

1. Clone the repository:
   ```bash/cmd
   git clone https://github.com/veg-salad/alya.git
   cd alya
   ```

---

## 🧾 Versioning

This repository uses **Git tags** for versioning.

- The latest stable release is: **[v1.0](https://github.com/veg-salad/alya/releases/tag/v1.0)**
- View all versions and changelogs in the [Releases](https://github.com/veg-salad/alya/releases) section.

To use a specific version:
```bash/cmd
git checkout tags/v1.0
```

> Versions follow semantic versioning: `MAJOR.MINOR.PATCH`
- `MAJOR`: Breaking changes
- `MINOR`: New features, backward-compatible
- `PATCH`: Bug fixes or improvements

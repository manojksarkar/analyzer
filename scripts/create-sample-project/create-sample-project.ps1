# Create the SampleCppProject in the running mock-api.
# Usage:   powershell -File create-sample-project.ps1
# Params (all optional):
param(
  [string]$BaseUrl  = "http://localhost:8000/api/v1",
  [string]$Email    = "alice@aspice.dev",
  [string]$Password = "secret"
)

$ErrorActionPreference = "Stop"

# 1) Sign in -> access token
$signin = Invoke-RestMethod -Method Post -Uri "$BaseUrl/auth/signin" `
  -ContentType "application/json" `
  -Body (@{ email = $Email; password = $Password } | ConvertTo-Json)
$token = $signin.access_token
Write-Host "Signed in as $Email" -ForegroundColor Green

# 2) Project payload
$payload = @'
{
  "name": "SampleCppProject",
  "client": "Reference",
  "compliance_standard": "ISO_26262",
  "repo_url": "https://github.com/vishal9359/SampleCppProject",
  "repo_provider": "github",
  "default_branch": "main",
  "access_token": null,
  "build_config": {
    "preprocessor_definitions": {
      "mode": "manual",
      "defines": ["FEATURE_A=1", "PLATFORM_EMBEDDED", "ENABLE_DIAG"]
    }
  },
  "architecture_layers": [
    {
      "name": "Layer1",
      "path": "Layer1",
      "groups": [
        {
          "name": "My Sample",
          "components": [
            { "name": "Sample Core", "files": ["Layer1/Sample/Core/Core.cpp", "Layer1/Sample/Core/Core.h"] },
            { "name": "Lib",         "files": ["Layer1/Sample/Lib/Lib.cpp", "Layer1/Sample/Lib/Lib.h"] },
            { "name": "Util",        "files": ["Layer1/Sample/Util/Util.cpp", "Layer1/Sample/Util/Util.h"] }
          ]
        },
        {
          "name": "Full",
          "components": [
            { "name": "Iface", "files": [
              "Layer1/Direction/ReadWrite.cpp", "Layer1/Direction/ReadWrite.h",
              "Layer1/Types/Types.cpp", "Layer1/Types/Types.h",
              "Layer1/Types/PointRect.cpp", "Layer1/Types/PointRect.h",
              "Layer1/Flow/Flowcharts.cpp", "Layer1/Flow/Flowcharts.h"
            ]},
            { "name": "Cross", "files": [
              "Layer1/Hub/Hub.cpp", "Layer1/Hub/Hub.h",
              "Layer1/Poly/Dispatch.cpp", "Layer1/Poly/Dispatch.h"
            ]}
          ]
        },
        {
          "name": "Support",
          "components": [
            { "name": "Math",  "files": ["Layer1/Math/Utils.cpp", "Layer1/Math/Utils.h"] },
            { "name": "App",   "files": ["Layer1/App/Main.cpp"] },
            { "name": "Outer", "files": ["Layer1/Outer/Inner/Helper.cpp", "Layer1/Outer/Inner/Helper.h"] }
          ]
        },
        {
          "name": "Access",
          "components": [
            { "name": "Access", "files": ["Layer1/Access/AccessVisibility.cpp", "Layer1/Access/AccessVisibility.h"] }
          ]
        },
        {
          "name": "Diag",
          "components": [
            { "name": "Diag", "files": [
              "Layer1/Diag/ForwardVoidDecl.cpp",
              "Layer1/Diag/MultilineOvlyinit.cpp",
              "Layer1/Diag/PreprocIfFunction.cpp",
              "Layer1/Diag/PreprocIfFunctionThen.cpp",
              "Layer1/Diag/VoidAsVar.cpp",
              "Layer1/Diag/VoidIsVoid.cpp"
            ]}
          ]
        }
      ]
    },
    {
      "name": "Layer2",
      "path": "Layer2",
      "groups": [
        {
          "name": "Platform",
          "components": [
            { "name": "Gpio", "files": [
              "Layer2/Platform/Gpio/Gpio.cpp", "Layer2/Platform/Gpio/Gpio.h",
              "Layer2/Platform/Gpio/GpioAlt.cpp", "Layer2/Platform/Gpio/GpioAlt.h",
              "Layer2/Platform/Gpio/GpioCfg.cpp", "Layer2/Platform/Gpio/GpioCfg.h",
              "Layer2/Platform/Gpio/GpioDebounce.cpp", "Layer2/Platform/Gpio/GpioDebounce.h",
              "Layer2/Platform/Gpio/GpioGroup.cpp", "Layer2/Platform/Gpio/GpioGroup.h",
              "Layer2/Platform/Gpio/GpioInput.cpp", "Layer2/Platform/Gpio/GpioInput.h",
              "Layer2/Platform/Gpio/GpioIrq.cpp", "Layer2/Platform/Gpio/GpioIrq.h",
              "Layer2/Platform/Gpio/GpioMux.cpp", "Layer2/Platform/Gpio/GpioMux.h",
              "Layer2/Platform/Gpio/GpioOutput.cpp", "Layer2/Platform/Gpio/GpioOutput.h",
              "Layer2/Platform/Gpio/GpioPin.cpp", "Layer2/Platform/Gpio/GpioPin.h",
              "Layer2/Platform/Gpio/GpioPort.cpp", "Layer2/Platform/Gpio/GpioPort.h"
            ]},
            { "name": "Uart", "files": [
              "Layer2/Platform/Uart/Uart.cpp", "Layer2/Platform/Uart/Uart.h",
              "Layer2/Platform/Uart/UartBuf.cpp", "Layer2/Platform/Uart/UartBuf.h",
              "Layer2/Platform/Uart/UartClock.cpp", "Layer2/Platform/Uart/UartClock.h",
              "Layer2/Platform/Uart/UartDebug.cpp", "Layer2/Platform/Uart/UartDebug.h",
              "Layer2/Platform/Uart/UartDma.cpp", "Layer2/Platform/Uart/UartDma.h",
              "Layer2/Platform/Uart/UartError.cpp", "Layer2/Platform/Uart/UartError.h",
              "Layer2/Platform/Uart/UartFifo.cpp", "Layer2/Platform/Uart/UartFifo.h",
              "Layer2/Platform/Uart/UartFlow.cpp", "Layer2/Platform/Uart/UartFlow.h",
              "Layer2/Platform/Uart/UartInit.cpp", "Layer2/Platform/Uart/UartInit.h",
              "Layer2/Platform/Uart/UartIrq.cpp", "Layer2/Platform/Uart/UartIrq.h",
              "Layer2/Platform/Uart/UartMode.cpp", "Layer2/Platform/Uart/UartMode.h",
              "Layer2/Platform/Uart/UartParity.cpp", "Layer2/Platform/Uart/UartParity.h",
              "Layer2/Platform/Uart/UartReset.cpp", "Layer2/Platform/Uart/UartReset.h",
              "Layer2/Platform/Uart/UartRx.cpp", "Layer2/Platform/Uart/UartRx.h",
              "Layer2/Platform/Uart/UartStop.cpp", "Layer2/Platform/Uart/UartStop.h",
              "Layer2/Platform/Uart/UartTx.cpp", "Layer2/Platform/Uart/UartTx.h"
            ]},
            { "name": "Spi", "files": [
              "Layer2/Platform/Spi/Spi.cpp", "Layer2/Platform/Spi/Spi.h",
              "Layer2/Platform/Spi/SpiCfg.cpp", "Layer2/Platform/Spi/SpiCfg.h",
              "Layer2/Platform/Spi/SpiDev.cpp", "Layer2/Platform/Spi/SpiDev.h"
            ]},
            { "name": "I2c", "files": [
              "Layer2/Platform/I2c/I2c.cpp", "Layer2/Platform/I2c/I2c.h",
              "Layer2/Platform/I2c/I2cMaster.cpp", "Layer2/Platform/I2c/I2cMaster.h",
              "Layer2/Platform/I2c/I2cScan.cpp", "Layer2/Platform/I2c/I2cScan.h"
            ]},
            { "name": "Adc", "files": [
              "Layer2/Platform/Adc/Adc.cpp", "Layer2/Platform/Adc/Adc.h",
              "Layer2/Platform/Adc/AdcCal.cpp", "Layer2/Platform/Adc/AdcCal.h",
              "Layer2/Platform/Adc/AdcFilter.cpp", "Layer2/Platform/Adc/AdcFilter.h"
            ]},
            { "name": "Display", "files": [
              "Layer2/Platform/Display/Display.cpp", "Layer2/Platform/Display/Display.h",
              "Layer2/Platform/Display/DispBuf.cpp", "Layer2/Platform/Display/DispBuf.h",
              "Layer2/Platform/Display/DispFont.cpp", "Layer2/Platform/Display/DispFont.h",
              "Layer2/Platform/Display/FrameBuf.cpp", "Layer2/Platform/Display/FrameBuf.h"
            ]},
            { "name": "Storage", "files": [
              "Layer2/Platform/Storage/Storage.cpp", "Layer2/Platform/Storage/Storage.h",
              "Layer2/Platform/Storage/Eeprom.cpp", "Layer2/Platform/Storage/Eeprom.h",
              "Layer2/Platform/Storage/Flash.cpp", "Layer2/Platform/Storage/Flash.h",
              "Layer2/Platform/Storage/StorCache.cpp", "Layer2/Platform/Storage/StorCache.h"
            ]},
            { "name": "Network", "files": [
              "Layer2/Platform/Network/Network.cpp", "Layer2/Platform/Network/Network.h",
              "Layer2/Platform/Network/NetBuf.cpp", "Layer2/Platform/Network/NetBuf.h",
              "Layer2/Platform/Network/Socket.cpp", "Layer2/Platform/Network/Socket.h",
              "Layer2/Platform/Network/TcpClient.cpp", "Layer2/Platform/Network/TcpClient.h"
            ]},
            { "name": "Logger", "files": [
              "Layer2/Platform/Logger/Logger.cpp", "Layer2/Platform/Logger/Logger.h",
              "Layer2/Platform/Logger/LogBuf.cpp", "Layer2/Platform/Logger/LogBuf.h",
              "Layer2/Platform/Logger/LogFmt.cpp", "Layer2/Platform/Logger/LogFmt.h"
            ]},
            { "name": "Config", "files": [
              "Layer2/Platform/Config/Config.cpp", "Layer2/Platform/Config/Config.h",
              "Layer2/Platform/Config/CfgParse.cpp", "Layer2/Platform/Config/CfgParse.h",
              "Layer2/Platform/Config/CfgStore.cpp", "Layer2/Platform/Config/CfgStore.h"
            ]},
            { "name": "EventBus", "files": [
              "Layer2/Platform/EventBus/EventBus.cpp", "Layer2/Platform/EventBus/EventBus.h",
              "Layer2/Platform/EventBus/EvbQueue.cpp", "Layer2/Platform/EventBus/EvbQueue.h",
              "Layer2/Platform/EventBus/Event.cpp", "Layer2/Platform/EventBus/Event.h"
            ]},
            { "name": "Timer", "files": [
              "Layer2/Platform/Timer/Timer.cpp", "Layer2/Platform/Timer/Timer.h",
              "Layer2/Platform/Timer/TmrHw.cpp", "Layer2/Platform/Timer/TmrHw.h",
              "Layer2/Platform/Timer/TmrMgr.cpp", "Layer2/Platform/Timer/TmrMgr.h"
            ]},
            { "name": "Protocol", "files": [
              "Layer2/Platform/Protocol/Protocol.cpp", "Layer2/Platform/Protocol/Protocol.h",
              "Layer2/Platform/Protocol/ProtoCrc.cpp", "Layer2/Platform/Protocol/ProtoCrc.h",
              "Layer2/Platform/Protocol/ProtoFrame.cpp", "Layer2/Platform/Protocol/ProtoFrame.h",
              "Layer2/Platform/Protocol/ProtoHdlr.cpp", "Layer2/Platform/Protocol/ProtoHdlr.h"
            ]},
            { "name": "Scheduler", "files": [
              "Layer2/Platform/Scheduler/Sched.cpp", "Layer2/Platform/Scheduler/Sched.h",
              "Layer2/Platform/Scheduler/SchedCfg.cpp", "Layer2/Platform/Scheduler/SchedCfg.h",
              "Layer2/Platform/Scheduler/Task.cpp", "Layer2/Platform/Scheduler/Task.h",
              "Layer2/Platform/Scheduler/TaskQueue.cpp", "Layer2/Platform/Scheduler/TaskQueue.h"
            ]},
            { "name": "Cache", "files": [
              "Layer2/Platform/Cache/Cache.cpp", "Layer2/Platform/Cache/Cache.h",
              "Layer2/Platform/Cache/CachePol.cpp", "Layer2/Platform/Cache/CachePol.h",
              "Layer2/Platform/Cache/LruCache.cpp", "Layer2/Platform/Cache/LruCache.h"
            ]}
          ]
        }
      ]
    },
    {
      "name": "Layer3",
      "path": "Layer3",
      "groups": []
    }
  ],
  "team": [
    { "email": "bob@aspice.dev",   "role": "developer" },
    { "email": "carol@aspice.dev", "role": "developer" },
    { "email": "eve@aspice.dev",   "role": "developer" }
  ]
}
'@

# 3) POST /projects
$resp = Invoke-RestMethod -Method Post -Uri "$BaseUrl/projects" `
  -Headers @{ Authorization = "Bearer $token" } `
  -ContentType "application/json" -Body $payload

Write-Host "Created project:" -ForegroundColor Green
Write-Host ("  id      = {0}" -f $resp.project.id)
Write-Host ("  name    = {0}" -f $resp.project.name)
Write-Host ("  status  = {0}" -f $resp.project.status)
Write-Host ("  my_role = {0}" -f $resp.project.my_role)

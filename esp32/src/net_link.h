#pragma once

#include <WiFi.h>
#include <BluetoothSerial.h>
#include <ArduinoJson.h>
#include "types.h"

class NetLink {
public:
  explicit NetLink(uint16_t port = 8765) : server_(port) {}
  void begin();
  void poll();
  bool linked();
  bool acceptSerialLine(const char *line);
  bool acceptBluetoothLine(const char *line);
  const Command &command() const { return command_; }
  void sendTelemetry(const CentralSnapshot &state, const SafetyReport &safety,
                     const MotionReport &motion, const CannonReport &cannon);
private:
  bool parse(const char *line, Command &output);
  void connectWifi();
  void pollBluetooth();
  WiFiServer server_;
  WiFiClient client_;
  BluetoothSerial bluetooth_;
  Command command_;
  char line_[1152] = {};
  char bt_line_[1152] = {};
  size_t used_ = 0;
  size_t bt_used_ = 0;
  unsigned long last_valid_ms_ = 0, last_wifi_attempt_ms_ = 0, last_mdns_attempt_ms_ = 0;
  // 0: sem enlace, 1: Wi-Fi, 2: USB, 3: Bluetooth SPP. Uma origem por vez.
  uint8_t active_transport_ = 0;
  bool server_started_ = false;
  bool mdns_started_ = false;
};

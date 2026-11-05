#pragma once

#include <WiFi.h>
#include <ArduinoJson.h>
#include "types.h"

class NetLink {
public:
  explicit NetLink(uint16_t port = 8765) : server_(port) {}
  void begin();
  void poll();
  bool linked();
  bool acceptSerialLine(const char *line);
  const Command &command() const { return command_; }
  void sendTelemetry(const CentralSnapshot &state, const SafetyReport &safety,
                     const MotionReport &motion, const CannonReport &cannon);
  void sendFastTelemetry(const CentralSnapshot &state, const MotionReport &motion,
                         const CannonReport &cannon);
private:
  bool parse(const char *line, Command &output);
  void connectWifi();
  void sendJsonLine(const JsonDocument &doc);
  WiFiServer server_;
  WiFiClient client_;
  Command command_;
  char line_[1152] = {};
  size_t used_ = 0;
  unsigned long last_valid_ms_ = 0, last_wifi_attempt_ms_ = 0, last_mdns_attempt_ms_ = 0;
  // 0: sem enlace, 1: Wi-Fi, 2: USB. Um meio por vez.
  uint8_t active_transport_ = 0;
  bool server_started_ = false;
  bool mdns_started_ = false;
};

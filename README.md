# Blynk IoT Integration

<p align="left">
  <img src="https://cdn.prod.website-files.com/6272e11601c9e296becde07b/665d3e23703fff50536fcae8_blynk-logo-green.svg" alt="Blynk Logo" width="300"/>
</p>

This integration is designed to manage your IoT projects through the Blynk platform. It provides easy control of common IoT devices like ESP8266 and ESP32, allowing you to expose your Blynk virtual pins as sensors, switches, and binary sensors in Home Assistant.

## Prerequisites

### Blynk App Setup

1. Create an account at [Blynk.io](https://blynk.io)
2. Create a new project
3. Note your Auth Token

### Method 1: HACS Installation (Recommended)
1. Make sure you have [HACS](https://hacs.xyz/) installed
2. Go to HACS > Integrations
3. Click the three dots in the top right and select "Custom Repository"
4. Add this repository URL: `https://github.com/Korkuttum/blynk`
5. Select "Integration" as category
6. Click "ADD"
7. Find and click on "Blynk" integration
8. Click "Download"
9. Restart Home Assistant

### Method 2: Manual Installation
Upload all files into the `custom_components/blynk` folder.

## Configuration

After installation:

1. Go to Settings > Devices & Services
2. Click "Add Integration"
3. Search for "Blynk"
4. Enter your Auth Token
5. Configure your device settings

---

## Support

If you find this integration helpful, consider supporting the development:

[![Become a Patreon](https://img.shields.io/badge/Become_a-Patron-red.svg?style=for-the-badge&logo=patreon)](https://www.patreon.com/korkuttum)

## License

MIT License - See [LICENSE](LICENSE) file for details.

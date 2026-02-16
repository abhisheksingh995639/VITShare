# VIT Share

**VIT Share** is a modern, cross-platform peer-to-peer (P2P) file sharing application designed for seamless file transfer between Windows desktops and Android devices over a local network.

<img width="1920" height="1020" alt="Screenshot 2026-02-10 172005" src="https://github.com/user-attachments/assets/3bd4bed5-737c-41d3-aa6f-92212b1ed076" />

## Features

- **Cross-Platform Support**: Effortlessly share files between Windows (Python Desktop App) and Android.
- **High-Speed Transfer**: Utilizes TCP/IP for fast and reliable data transmission over local Wi-Fi.
- **No Internet Required**: Works entirely offline on a local network or hotspot.
- **Easy Connection**: Quick pairing via QR Code scanning.
- **Drag & Drop Interface**: Simple drag-and-drop file sharing on the desktop app.
- **Modern UI**: Clean and intuitive dark mode interface using `customtkinter`.
- **Directory Support**: Transfer entire folders (automatically zipped and unzipped).

## Project Structure

- **Desktop Client**: `FileShare11.py` - A Python-based desktop application.
- **Mobile Client**: `app/` - An Android application (Kotlin/Java).

---

## Desktop Client (Python)

### Prerequisites

- Python 3.x installed.
- `pip` package manager.

### Installation

1.  Clone the repository or download the source code.
2.  Install the required Python libraries:

    ```bash
    pip install customtkinter tkinterdnd2 qrcode Pillow
    ```

    *Note: `tkinterdnd2` acts as a wrapper for drag-and-drop functionality in `tkinter`.*

### Running the Application

1.  Navigate to the project directory.
2.  Run the Python script:

    ```bash
    python FileShare11.py
    ```

3.  The application window will open. You can now:
    -   Click **"Show My QR Code"** to display a QR code for mobile connection.
    -   **Drag and drop files** into the "My Files" area to prepare them for sending.
    -   See connected peers in the "Connected Devices" list.

---

## Mobile Client (Android)

### Prerequisites

- Android Studio (for building the app).
- Android Device (Android 12+ recommended).

### Building and Installation

1.  Open Android Studio.
2.  Select **"Open an existing Android Studio project"** and navigate to the `app` folder within this repository.
3.  Let Gradle sync the project dependencies.
4.  Connect your Android device via USB (with USB Debugging enabled) or use an emulator.
5.  Click the **Run** button (green play icon) in Android Studio to build and install the app on your device.

### Permissions

The app requires the following permissions to function correctly:
-   **Location / Nearby Devices**: To discover peers on the local network.
-   **Camera**: To scan the QR code for connection.
-   **Storage**: To save received files to your device.

---

## How to Use

1.  **Connect to the same Wi-Fi**: Ensure both your Windows PC and Android device are connected to the same Wi-Fi network (or one is connected to the other's hotspot).
2.  **Start the Desktop App**: Run `FileShare11.py` on your PC.
3.  **Open the Android App**: Launch the VIT Share app on your phone.
4.  **Pair Devices**:
    -   On the Desktop App, click **"Show My QR Code"**.
    -   On the Android App, use the **Scan QR** feature to scan the code displayed on your PC screen.
5.  **Transfer Files**:
    -   **Send from PC**: Drag and drop files into the desktop app, or use "Add Files". Select the recipient from the "Connected Devices" list and click "Send".
    -   **Send from Android**: Select files within the app and choose the connected PC as the destination.
6.  **Receive Files**: Incoming transfers will appear in the "Receiving" section. Files are automatically saved to the `Downloads/P2P File Sharer Data` folder (or similar, depending on OS).

## Troubleshooting

-   **Connection Failed**: Ensure both devices are on the *same* network. Disable AP Isolation on your router if enabled. Check Windows Firewall settings to allow Python to communicate on private networks.
-   **QR Code Not Scanning**: Ensure adequate lighting and camera permissions are granted on the Android app.
-   **Missing Dependencies**: Double-check that all Python libraries (`customtkinter`, `tkinterdnd2`, etc.) are installed correctly.

## License

[MIT License](LICENSE) (Assuming MIT Use as per standard open-source norms, please update if different)


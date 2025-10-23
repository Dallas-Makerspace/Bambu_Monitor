# Bambu_Monitor 
  - Python program to track Bambu printer usage trends in Google Sheets
  - Uses Waydroid emulator, Android debugger (ADB), and Bambu Handy app

## Components
  - main.py - main thread
  - job_store.py - dataclass for jobs
  - controller.py - utility for screen control 
  - parser.py - utility for extracting screen information
  - gspread_updater.py - utility for interacting with google sheets
  - supervisor.py - Performs startup sequence and takes care of restarts
  - waydroid-daemon.service - Daemon service to initiate launch on startup
  - /BambuHandy - contains the android app
  - /secret.zip - client secret for google service account (encrypted)

## Raspberry Pi Setup instructions

### 1) Update
```
sudo apt update
sudo apt upgrade -y
```
### 2) Required OS Configuration
```
# Pressure stall information
sudo sed -i '/psi=1/! s/$/ psi=1/' /boot/firmware/cmdline.txt
# Page size of 4096
sudo grep -qxF 'kernel=kernel8.img' /boot/firmware/config.txt || sudo sed -i '1ikernel=kernel8.img' /boot/firmware/config.txt
```
### 3) Reboot
```
sudo reboot
```
### 4) Install secret using 3dFab password (iykyk)
```
unzip secret.zip
```
### 5) Install dependencies
```
sudo apt install adb curl lsb-release python3 python3-pip python3-venv -y
python3 -m venv handy_env
source handy_env/bin/activate
pip install -r requirements.txt
```
### 6) Install Waydroid
```
sudo curl -Sf https://repo.waydro.id/waydroid.gpg --output /usr/share/keyrings/waydroid.gpg
echo "deb [signed-by=/usr/share/keyrings/waydroid.gpg] https://repo.waydro.id/ $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/waydroid.list
sudo apt update
sudo apt install waydroid -y
sudo waydroid init
waydroid show-full-ui
```
### 7) manual step - enable debug mode on android and get android ip address
> tap on the build number 7 times
> 
> ensure usb debugging is enabled (should be default)
> 
> ensure android timezone matches system time
### 8) Install Bambu Handy
```
unzip BambuHandy/'*.zip' -d BambuHandy
adb connect 192.168.240.112
adb install-multiple ./BambuHandy/*.apk
```
### 9) manual step - launch bambu handy and login

### 10) Create and start user daemon 
  - Note: replace USER in waydroid-daemon.service with username 
  ```
# Copy service file to user systemd directory
mkdir -p ~/.config/systemd/user
cp -v waydroid-daemon.service ~/.config/systemd/user/

# Set permissions
chmod 644 ~/.config/systemd/user/waydroid-daemon.service

# Reload systemd user daemon and enable service
systemctl --user daemon-reload
systemctl --user enable waydroid-daemon
systemctl --user restart waydroid-daemon

# (Optional) Check status and logs
systemctl --user status waydroid-daemon
journalctl --user -u waydroid-daemon -f
```

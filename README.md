# Bambu_Monitor - Python program to monitor bambu printers and update google sheets
# Uses waydroid, android debugger, and of course bambu, handy

#  ---Components---
# main.py - main thread
# job_store.py - dataclass for jobs
# controller.py - utility for screen control 
# parser.py - utility for extracting screen information
# gspread_updater.py - utility for interacting with google sheets
# Supervisor.py - Performs startup sequence and takes care of restarts
# waydroid-supervisor.service - Daemon service to initiate launch on startup
# /BambuHandy.zip - contains the APK 
# /Secret.zip - client secret for google service account (encrypted)
# README.md - see README.md for further explanation

# ---Setup instructions---

# Update
sudo apt update
sudo apt upgrade -y
# Enable pressure stall information
sudo sh -c 'echo "psi=1" >> /boot/firmware/cmdline.txt'
# Reboot
sudo reboot

# Install secret using 3dFab password (iykyk)
unzip secret.zip

# Instal dependencies 
sudo apt install curl lsb-release python3 python3-pip python3-venv -y
pip install -r requirements.txt --break-system-packages

# Install Waydroid
sudo curl -Sf https://repo.waydro.id/waydroid.gpg --output /usr/share/keyrings/waydroid.gpg
echo "deb [signed-by=/usr/share/keyrings/waydroid.gpg] https://repo.waydro.id/ $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/waydroid.list
sudo apt update
sudo apt install waydroid
sudo waydroid init
waydroid show-full-ui

#
# manual step - enable debug mode on android and get android ip address
#

# Install Bambu Handy
ANDROID_IP = PUT_IP_HERE
unzip BambuHandy/'*.zip' -d BambuHandy
adb connect $ANDROID_IP
adb install-multiple ./BambuHandy/*.apk

#
# manual step - launch bambu handy and login 
#

# Create and start daemon - Note: replace USER in supervisor.service with username
sudo cp -v waydroid-supervisor.service /etc/systemd/system/
chmod 644 /etc/systemd/system/waydroid-supervisor.service
systemctl daemon-reload
systemctl enable waydroid-supervisor
systemctl restart waydroid-supervisor


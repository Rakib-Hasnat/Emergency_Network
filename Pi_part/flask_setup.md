# Flask Environment Setup (Raspberry Pi)

**Step 1.**
```
sudo apt update
sudo apt upgrade -y
```
Update Raspberry Pi.

**Step 2.**
```
sudo apt install python3-venv python3-full -y
```
Install venv support.

**Step 3. Create a virtual environment**
```
cd ~/Redemption
python3 -m venv flask_env
```
`cd` into your desired path first — this creates a `flask_env` folder inside it.

**Step 4. Activate the environment**
```
source ~/Redemption/flask_env/bin/activate
```
You'll see:
```
(flask_env) akash@pi:~/Redemption $
```
This means it's active.

**Step 5. Install Flask**
```
pip install flask
```
⚠️ No `sudo`.

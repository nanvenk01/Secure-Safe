# Secure-Safe  
### Made by: Archisa Arora & Nandini Venkatesh  

**SecureSafe** is the Senior Capstone Project developed at the Edison Academy Magnet School, combining over three years of Electrical Engineering and Computer Science coursework. This project integrates both hardware and software components to create a secure, user-friendly, multi-factor authentication (MFA) door locking and unlocking system.

This repository contains the complete codebase and interface files for SecureSafe. The system is deployed on a Raspberry Pi and controls a rack-and-pinion locking mechanism and a four-bar linkage system (designed by the Civil/Mechanical team) to physically open the door. 

---

## Project Overview

SecureSafe allows a user to unlock a secure entryway using **two layers of authentication**:
1. A **randomly-generated PIN code** sent via email
2. A **validated fingerprint scan**

### Electrical Engineering Components:
- Raspberry Pi 4  
- PCA9685 PWM driver  
- Axon Servos and GoBILDA Motors 
- Optical Fingerprint Sensor which uses UART (Universal Asynchronous Reciever-Transmitter)

### Computer Science Stack:
- Python: used to program all backend logic  
- Flask API: to bridge the backend with the user-facing interface  
- HTML/CSS: to build a clean and functional front end  
- Firebase: to manage user accounts and securely store fingerprints and credentials  
- SMTP (Simple Mail Transfer Protocol): to securely send PINs via email as part of the authentication process 

---

## How to Run the Code

1. **Download** the entire repository and open it as a new project on your local machine.  
2. **Set up your SMTP email server**:  
   - In `app.py`, insert your email and app-specific password to enable email-based PIN sending.  
   - Make sure to enable “less secure app access” or use an app password if you're using Gmail.  
3. **Set up Firebase**:  
   - Create a Firebase project and insert your credentials and database URL in the appropriate configuration files.  
4. **Run the project**:  
   - From the terminal, run `python app.py`.  
   - This will start the Flask server, allowing users to interact with the interface and trigger the Raspberry Pi.

> Note: The project was hosted locally for demo purposes but can be deployed on a remote server for broader access.

Thanks for checking out SecureSafe! 🚪🔒

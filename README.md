# TLSOC Log Parser Stack

Welcome to the **TLSOC** repository. This project contains an integrated, containerized version of the FOSS SOC Engine and ELK Stack (Elasticsearch, Logstash, Kibana) tailored for security log collection, parsing, normalisation, and threat detection.

---

## Deployment & Setup Guide (Step-by-Step)

Follow these steps in order to set up your environment, launch the services, and manually configure the Kibana visualization dashboards and SIEM detection rules.

### Phase 1: Prerequisites & Host Preparation

Before launching the containers, ensure your machine is ready:
1. **Docker Desktop (Windows/Mac)**: Ensure Docker Desktop is installed and running (verify the status is "Engine Running" / green).
2. **WSL 2 (Windows)**: Ensure WSL2 is installed and set as your Docker backend for optimal performance.
3. **Linux Host Memory Configuration (Ubuntu/Debian)**: Elasticsearch requires a large virtual memory map count. Run this in your host terminal to prevent instant crash:
   ```bash
   sudo sysctl -w vm.max_map_count=262144
   ```
   *(To persist across system reboots, add `vm.max_map_count=262144` to your `/etc/sysctl.conf`)*

---

### Phase 2: Configuration Setup

#### 1. Environment variables (`.env`)
In the root directory, open or create a `.env` file:
```env
ELASTIC_VERSION=8.19.12
ELASTIC_PASSWORD=YourSecureElasticPassword
KIBANA_PASSWORD=YourSecureKibanaSystemPassword
HOST_IP= 127.0.0.1  # Change this to your host's local IP address


#### 2. Engine Configuration
Open `engine/config.yaml` to configure the engine connection details:
- **`bootstrap_servers`**: Ensure this points to your Kafka broker (e.g., `["kafka:9092"]` for local or `["192.168.10.62:9094"]` for production).
- **`group_id`**: Update this to a unique identifier if multiple developers are consuming from the same production Kafka server simultaneously to prevent offset conflict.

---

### Phase 3: Launching the Stack

#### Step 1: Generate TLS Certificates
Elasticsearch requires self-signed certificates. Run the generation script from the root directory:
```bash
bash certs/generate-certs.sh
```
This generates the required TLS credentials inside the `./certs` folder.

#### Step 2: Deploy Containers
Build and boot the services in the background:
```bash
docker compose up -d --build
```
> [!NOTE]
> The `--build` flag is required on the first deploy to compile the custom Python engine image and GeoIP dependencies.

Verify all containers are up and running:
```bash
docker compose ps
```

Wait **2-3 minutes** for Elasticsearch and Kibana to initialize completely.

---

### Phase 4: Manual Kibana Space & Saved Objects Setup

Once Kibana is running, open your web browser and navigate to `https://localhost:5601`. Log in using the username `elastic` and the password you defined in `.env`.

Follow these manual steps to configure the custom TLSOC Space:

#### 1. Create the TLSOC Space
1. Go to **Stack Management** (bottom left gear icon).
2. Under Kibana, click on **Spaces**.
3. Click the **Create a space** button in the top right.
4. Fill in the following exact details:
   - **Name:** `TLSOC`
   - **URL identifier:** `tlsoc` (This must be exactly `tlsoc`)
   - **Avatar Image**: Select the Image tab and upload your `logo.png` from the `setup/` folder.
   - **Background color:** `#6092C0`
5. *(Optional)* Under **Features**, you can click the **Solution view** dropdown and select **Security** to automatically hide irrelevant Kibana menus.
6. Click **Create space**.

> [!IMPORTANT]
> **Switch to your new Space!** Before proceeding to the next steps, click the avatar icon in the absolute top-left corner of Kibana and switch your current environment from `Default` to `TLSOC`. If you don't do this, you will accidentally import everything into the wrong space.

#### 2. Manually Inject Required Data Views
The SIEM rules and Dashboards are hardcoded to look for Data Views with specific internal UUIDs. You must inject them manually:
1. Navigate to **Stack Management** -> **Data Views**.
2. Click **Create data view**.
   - **Name:** `SIEM Rule View 1`
   - **Index pattern:** `fosstlsoc-logs-*`
3. Click **Show advanced settings** at the bottom.
4. **Data view ID:** Paste `4ea16e42-92a0-4495-a6c1-a1848eb235f6`
5. Click **Save data view to Kibana**.

Repeat the process for the second required view:
1. Click **Create data view** again.
   - **Name:** `SIEM Rule View 2`
   - **Index pattern:** `fosstlsoc-logs-*`
2. **Data view ID:** Paste `60b3f25a-9745-44fb-95c8-f1b5e8c5b3c8`
3. Click **Save data view to Kibana**.

#### 3. Import Dashboards & Saved Objects
1. Navigate to **Stack Management** -> **Saved Objects**.
2. Click **Import** in the top right corner.
3. Select your `setup/dashboards.ndjson` file.
4. Toggle the **Automatically overwrite all saved objects** switch to ON.
5. Click **Import**.
6. You should see a success message indicating 17 objects were imported.

#### 4. Import SIEM Detection Rules
1. Navigate to the **Security** app from the main left-hand menu.
2. Under the Security menu, go to **Manage** -> **Rules**.
3. Click the **Import rules** button.
4. Select your `setup/rules.ndjson` file.
5. Ensure the **Overwrite existing rules** checkbox is selected.
6. Click **Import**.
7. You should see a success message indicating 20 rules were imported.

> [!TIP]
> After importing, some rules may throw "Unknown column" verification exceptions for a few minutes. This is normal behavior when Elasticsearch is mapping a brand-new database and will automatically resolve itself as real logs start flowing into the system.

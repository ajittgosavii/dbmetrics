# integrated_streamlit_app.py
"""
Cloud-ready Streamlit app with integrated database metrics collection
Combines your existing RDS analysis with real-time on-premise database monitoring
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import asyncio
import json
import sqlite3
import threading
import time
import logging
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional
import os

# Database connectors - install these in requirements.txt
try:
    import cx_Oracle
    ORACLE_AVAILABLE = True
except ImportError:
    ORACLE_AVAILABLE = False

try:
    import pymysql
    MYSQL_AVAILABLE = True
except ImportError:
    MYSQL_AVAILABLE = False

try:
    import pyodbc
    SQLSERVER_AVAILABLE = True
except ImportError:
    SQLSERVER_AVAILABLE = False

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

# Configure Streamlit page
st.set_page_config(
    page_title="Database Migration Analyzer",
    page_icon="🔄",
    layout="wide",
    initial_sidebar_state="expanded"
)

@dataclass
class DatabaseConfig:
    """Database configuration for on-premise databases"""
    name: str
    type: str  # oracle, mysql, sqlserver
    host: str
    port: int
    database: str
    username: str
    password: str
    environment: str = "production"
    enabled: bool = True

@dataclass
class DatabaseMetrics:
    """Database metrics data structure"""
    database_name: str
    timestamp: datetime
    cpu_usage_percent: float = 0
    memory_usage_percent: float = 0
    memory_total_gb: float = 0
    active_connections: int = 0
    max_connections: int = 0
    connection_usage_percent: float = 0
    avg_query_time_ms: float = 0
    slow_queries_per_hour: int = 0
    queries_per_second: float = 0
    buffer_hit_ratio: float = 0
    database_size_gb: float = 0
    read_operations_per_sec: float = 0
    write_operations_per_sec: float = 0
    read_write_ratio: float = 0
    collection_status: str = "success"
    error_message: str = ""

class DatabaseMetricsCollector:
    """Integrated database metrics collector for Streamlit cloud deployment"""
    
    def __init__(self):
        self.logger = self._setup_logging()
        
    def _setup_logging(self):
        """Setup logging for Streamlit cloud"""
        logging.basicConfig(level=logging.INFO)
        return logging.getLogger(__name__)
    
    def get_system_metrics(self) -> Dict:
        """Get system metrics with fallbacks for cloud deployment"""
        try:
            if PSUTIL_AVAILABLE:
                # Try to get system metrics
                cpu_percent = psutil.cpu_percent(interval=1)
                memory = psutil.virtual_memory()
                memory_total_gb = memory.total / (1024**3)
                memory_percent = memory.percent
            else:
                # Fallback values when psutil is not available
                cpu_percent = 0
                memory_total_gb = 16  # Default assumption
                memory_percent = 0
                
            return {
                'cpu_usage_percent': cpu_percent,
                'memory_usage_percent': memory_percent,
                'memory_total_gb': memory_total_gb,
            }
        except Exception as e:
            self.logger.warning(f"Could not get system metrics: {e}")
            return {
                'cpu_usage_percent': 0,
                'memory_usage_percent': 0,
                'memory_total_gb': 16,
            }
    
    def collect_oracle_metrics(self, config: DatabaseConfig) -> DatabaseMetrics:
        """Collect Oracle database metrics"""
        if not ORACLE_AVAILABLE:
            raise Exception("cx_Oracle package not available")
            
        try:
            # Connect to Oracle
            dsn = cx_Oracle.makedsn(config.host, config.port, service_name=config.database)
            connection = cx_Oracle.connect(config.username, config.password, dsn)
            cursor = connection.cursor()
            
            system_metrics = self.get_system_metrics()
            
            # Active connections
            cursor.execute("SELECT COUNT(*) FROM v$session WHERE status = 'ACTIVE' AND type = 'USER'")
            active_connections = cursor.fetchone()[0]
            
            # Max connections
            cursor.execute("SELECT value FROM v$parameter WHERE name = 'sessions'")
            max_connections = int(cursor.fetchone()[0])
            
            # Buffer hit ratio
            cursor.execute("""
                SELECT (1 - (phy.value / (db.value + phy.value))) * 100 as buffer_hit_ratio
                FROM v$sysstat phy, v$sysstat db
                WHERE phy.name = 'physical reads'
                AND db.name = 'db block gets'
            """)
            buffer_hit_ratio = cursor.fetchone()[0] or 0
            
            # Database size
            cursor.execute("SELECT SUM(bytes)/(1024*1024*1024) FROM dba_data_files")
            database_size_gb = cursor.fetchone()[0] or 0
            
            # Query performance (simplified for cloud)
            cursor.execute("""
                SELECT 
                    AVG(elapsed_time/executions/1000) as avg_query_time_ms,
                    SUM(executions) as total_executions
                FROM v$sql 
                WHERE executions > 0 AND elapsed_time > 0
                AND last_active_time > SYSDATE - 1/24
                AND ROWNUM <= 1000
            """)
            query_perf = cursor.fetchone()
            avg_query_time_ms = query_perf[0] or 0
            total_executions = query_perf[1] or 0
            queries_per_second = total_executions / 3600 if total_executions else 0
            
            cursor.close()
            connection.close()
            
            return DatabaseMetrics(
                database_name=config.name,
                timestamp=datetime.now(),
                cpu_usage_percent=system_metrics['cpu_usage_percent'],
                memory_usage_percent=system_metrics['memory_usage_percent'],
                memory_total_gb=system_metrics['memory_total_gb'],
                active_connections=active_connections,
                max_connections=max_connections,
                connection_usage_percent=(active_connections / max_connections) * 100,
                avg_query_time_ms=avg_query_time_ms,
                queries_per_second=queries_per_second,
                buffer_hit_ratio=buffer_hit_ratio,
                database_size_gb=database_size_gb,
                read_write_ratio=2.0  # Default assumption for Oracle
            )
            
        except Exception as e:
            self.logger.error(f"Oracle metrics collection failed: {e}")
            return DatabaseMetrics(
                database_name=config.name,
                timestamp=datetime.now(),
                collection_status="error",
                error_message=str(e)
            )
    
    def collect_mysql_metrics(self, config: DatabaseConfig) -> DatabaseMetrics:
        """Collect MySQL database metrics"""
        if not MYSQL_AVAILABLE:
            raise Exception("PyMySQL package not available")
            
        try:
            # Connect to MySQL
            connection = pymysql.connect(
                host=config.host,
                port=config.port,
                user=config.username,
                password=config.password,
                database=config.database,
                charset='utf8mb4'
            )
            cursor = connection.cursor()
            
            system_metrics = self.get_system_metrics()
            
            # Connection metrics
            cursor.execute("SHOW STATUS LIKE 'Threads_connected'")
            active_connections = int(cursor.fetchone()[1])
            
            cursor.execute("SHOW VARIABLES LIKE 'max_connections'")
            max_connections = int(cursor.fetchone()[1])
            
            # Buffer pool hit ratio
            cursor.execute("SHOW STATUS LIKE 'Innodb_buffer_pool_read_requests'")
            read_requests = int(cursor.fetchone()[1])
            
            cursor.execute("SHOW STATUS LIKE 'Innodb_buffer_pool_reads'")
            disk_reads = int(cursor.fetchone()[1])
            
            buffer_hit_ratio = ((read_requests - disk_reads) / read_requests) * 100 if read_requests > 0 else 0
            
            # Database size
            cursor.execute(f"""
                SELECT ROUND(SUM(data_length + index_length) / 1024 / 1024 / 1024, 2)
                FROM information_schema.tables 
                WHERE table_schema = '{config.database}'
            """)
            database_size_gb = float(cursor.fetchone()[0] or 0)
            
            # Query performance
            cursor.execute("SHOW STATUS LIKE 'Questions'")
            total_queries = int(cursor.fetchone()[1])
            
            cursor.execute("SHOW STATUS LIKE 'Uptime'")
            uptime = int(cursor.fetchone()[1])
            queries_per_second = total_queries / uptime if uptime > 0 else 0
            
            cursor.close()
            connection.close()
            
            return DatabaseMetrics(
                database_name=config.name,
                timestamp=datetime.now(),
                cpu_usage_percent=system_metrics['cpu_usage_percent'],
                memory_usage_percent=system_metrics['memory_usage_percent'],
                memory_total_gb=system_metrics['memory_total_gb'],
                active_connections=active_connections,
                max_connections=max_connections,
                connection_usage_percent=(active_connections / max_connections) * 100,
                queries_per_second=queries_per_second,
                buffer_hit_ratio=buffer_hit_ratio,
                database_size_gb=database_size_gb,
                read_write_ratio=3.0  # Default assumption for MySQL
            )
            
        except Exception as e:
            self.logger.error(f"MySQL metrics collection failed: {e}")
            return DatabaseMetrics(
                database_name=config.name,
                timestamp=datetime.now(),
                collection_status="error",
                error_message=str(e)
            )
    
    def collect_sqlserver_metrics(self, config: DatabaseConfig) -> DatabaseMetrics:
        """Collect SQL Server database metrics"""
        if not SQLSERVER_AVAILABLE:
            raise Exception("pyodbc package not available")
            
        try:
            # Connect to SQL Server
            connection_string = (
                f"DRIVER={{ODBC Driver 17 for SQL Server}};"
                f"SERVER={config.host},{config.port};"
                f"DATABASE={config.database};"
                f"UID={config.username};"
                f"PWD={config.password}"
            )
            connection = pyodbc.connect(connection_string)
            cursor = connection.cursor()
            
            system_metrics = self.get_system_metrics()
            
            # Connection metrics
            cursor.execute("""
                SELECT COUNT(*) FROM sys.dm_exec_sessions 
                WHERE is_user_process = 1 AND status = 'running'
            """)
            active_connections = cursor.fetchone()[0]
            
            cursor.execute("SELECT @@MAX_CONNECTIONS")
            max_connections = cursor.fetchone()[0]
            
            # Database size
            cursor.execute(f"""
                SELECT SUM(size * 8.0 / 1024 / 1024)
                FROM sys.master_files 
                WHERE database_id = DB_ID('{config.database}')
                AND type = 0
            """)
            database_size_gb = cursor.fetchone()[0] or 0
            
            cursor.close()
            connection.close()
            
            return DatabaseMetrics(
                database_name=config.name,
                timestamp=datetime.now(),
                cpu_usage_percent=system_metrics['cpu_usage_percent'],
                memory_usage_percent=system_metrics['memory_usage_percent'],
                memory_total_gb=system_metrics['memory_total_gb'],
                active_connections=active_connections,
                max_connections=max_connections,
                connection_usage_percent=(active_connections / max_connections) * 100,
                database_size_gb=database_size_gb,
                buffer_hit_ratio=85.0,  # Default assumption
                read_write_ratio=2.5  # Default assumption
            )
            
        except Exception as e:
            self.logger.error(f"SQL Server metrics collection failed: {e}")
            return DatabaseMetrics(
                database_name=config.name,
                timestamp=datetime.now(),
                collection_status="error",
                error_message=str(e)
            )
    
    def collect_metrics_for_database(self, config: DatabaseConfig) -> DatabaseMetrics:
        """Collect metrics for a single database"""
        if not config.enabled:
            return None
            
        try:
            if config.type.lower() == "oracle":
                return self.collect_oracle_metrics(config)
            elif config.type.lower() == "mysql":
                return self.collect_mysql_metrics(config)
            elif config.type.lower() == "sqlserver":
                return self.collect_sqlserver_metrics(config)
            else:
                raise ValueError(f"Unsupported database type: {config.type}")
        except Exception as e:
            self.logger.error(f"Error collecting metrics for {config.name}: {e}")
            return DatabaseMetrics(
                database_name=config.name,
                timestamp=datetime.now(),
                collection_status="error",
                error_message=str(e)
            )

def get_database_configs() -> List[DatabaseConfig]:
    """Get database configurations from Streamlit secrets or session state"""
    
    # Try to get from Streamlit secrets first
    if hasattr(st, 'secrets') and 'databases' in st.secrets:
        try:
            databases = []
            for db_config in st.secrets['databases']:
                databases.append(DatabaseConfig(**db_config))
            return databases
        except Exception as e:
            st.error(f"Error loading database configs from secrets: {e}")
    
    # Fallback to session state or manual configuration
    if 'database_configs' not in st.session_state:
        st.session_state.database_configs = []
    
    return st.session_state.database_configs

def show_database_configuration():
    """Show database configuration interface"""
    st.markdown("## ⚙️ Database Configuration")
    st.info("Configure your on-premise databases for monitoring and migration analysis.")
    
    # Check for required packages
    missing_packages = []
    if not ORACLE_AVAILABLE:
        missing_packages.append("cx_Oracle")
    if not MYSQL_AVAILABLE:
        missing_packages.append("PyMySQL") 
    if not SQLSERVER_AVAILABLE:
        missing_packages.append("pyodbc")
    
    if missing_packages:
        st.warning(f"⚠️ Missing packages: {', '.join(missing_packages)}. Install them to enable full database support.")
    
    # Configuration options
    config_method = st.radio(
        "Configuration Method:",
        ["Manual Entry", "Streamlit Secrets", "Upload Config File"],
        help="Choose how to configure your database connections"
    )
    
    if config_method == "Manual Entry":
        show_manual_database_config()
    elif config_method == "Streamlit Secrets":
        show_secrets_config_guide()
    else:
        show_file_upload_config()

def show_manual_database_config():
    """Show manual database configuration interface"""
    
    st.markdown("### 📝 Manual Database Configuration")
    
    # Current configurations
    configs = get_database_configs()
    
    if configs:
        st.markdown("#### Current Configurations:")
        for i, config in enumerate(configs):
            col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
            
            with col1:
                status_icon = "✅" if config.enabled else "❌"
                st.write(f"{status_icon} **{config.name}** ({config.type}) - {config.host}:{config.port}")
            
            with col2:
                if st.button("✏️ Edit", key=f"edit_{i}"):
                    st.session_state[f'editing_config_{i}'] = True
            
            with col3:
                enabled = st.checkbox("Enabled", value=config.enabled, key=f"enabled_{i}")
                configs[i].enabled = enabled
            
            with col4:
                if st.button("🗑️ Delete", key=f"delete_{i}"):
                    configs.pop(i)
                    st.session_state.database_configs = configs
                    st.rerun()
    
    # Add new database configuration
    st.markdown("#### Add New Database:")
    
    with st.form("add_database"):
        col1, col2 = st.columns(2)
        
        with col1:
            name = st.text_input("Database Name", placeholder="production_oracle")
            db_type = st.selectbox("Database Type", ["oracle", "mysql", "sqlserver"])
            host = st.text_input("Host", placeholder="db-server.company.com")
            port = st.number_input("Port", value=1521 if db_type == "oracle" else 3306 if db_type == "mysql" else 1433)
        
        with col2:
            database = st.text_input("Database/Service Name", placeholder="PROD")
            username = st.text_input("Username", placeholder="monitor_user")
            password = st.text_input("Password", type="password")
            environment = st.selectbox("Environment", ["production", "staging", "development"])
        
        if st.form_submit_button("➕ Add Database"):
            if all([name, host, database, username, password]):
                new_config = DatabaseConfig(
                    name=name,
                    type=db_type,
                    host=host,
                    port=port,
                    database=database,
                    username=username,
                    password=password,
                    environment=environment,
                    enabled=True
                )
                
                if 'database_configs' not in st.session_state:
                    st.session_state.database_configs = []
                
                st.session_state.database_configs.append(new_config)
                st.success(f"✅ Added {name} configuration!")
                st.rerun()
            else:
                st.error("❌ Please fill in all required fields")

def show_secrets_config_guide():
    """Show guide for configuring databases via Streamlit secrets"""
    
    st.markdown("### 🔐 Streamlit Secrets Configuration")
    st.info("For production deployments, use Streamlit secrets to securely store database credentials.")
    
    st.markdown("#### 1. Create `.streamlit/secrets.toml` file:")
    
    secrets_example = '''
[databases]

[[databases]]
name = "production_oracle"
type = "oracle"
host = "oracle-prod.company.com"
port = 1521
database = "PROD"
username = "monitor_user"
password = "your_secure_password"
environment = "production"
enabled = true

[[databases]]
name = "analytics_mysql"
type = "mysql"
host = "mysql-analytics.company.com" 
port = 3306
database = "analytics"
username = "monitor_user"
password = "your_secure_password"
environment = "production"
enabled = true

[[databases]]
name = "reporting_sqlserver"
type = "sqlserver"
host = "sqlserver-reporting.company.com"
port = 1433
database = "Reporting"
username = "monitor_user"
password = "your_secure_password"
environment = "production"
enabled = true
'''
    
    st.code(secrets_example, language="toml")
    
    st.markdown("#### 2. For Streamlit Cloud deployment:")
    st.markdown("- Go to your app dashboard")
    st.markdown("- Click on 'Advanced settings'")
    st.markdown("- Add your database configurations in the secrets section")
    
    # Test secrets loading
    if st.button("🧪 Test Secrets Loading"):
        try:
            configs = get_database_configs()
            if configs:
                st.success(f"✅ Successfully loaded {len(configs)} database configurations from secrets!")
                for config in configs:
                    st.write(f"- {config.name} ({config.type})")
            else:
                st.warning("⚠️ No database configurations found in secrets")
        except Exception as e:
            st.error(f"❌ Error loading secrets: {e}")

def show_file_upload_config():
    """Show file upload configuration interface"""
    
    st.markdown("### 📁 Upload Configuration File")
    
    uploaded_file = st.file_uploader(
        "Upload database configuration JSON file:",
        type=['json'],
        help="Upload a JSON file containing your database configurations"
    )
    
    if uploaded_file is not None:
        try:
            config_data = json.load(uploaded_file)
            
            if 'databases' in config_data:
                configs = []
                for db_config in config_data['databases']:
                    configs.append(DatabaseConfig(**db_config))
                
                st.session_state.database_configs = configs
                st.success(f"✅ Successfully loaded {len(configs)} database configurations!")
                
                # Show loaded configurations
                for config in configs:
                    st.write(f"- {config.name} ({config.type}) - {config.host}:{config.port}")
            else:
                st.error("❌ Invalid configuration file format")
                
        except Exception as e:
            st.error(f"❌ Error loading configuration file: {e}")
    
    # Show example format
    if st.expander("📋 Example Configuration File Format"):
        example_config = {
            "databases": [
                {
                    "name": "production_oracle",
                    "type": "oracle",
                    "host": "oracle-prod.company.com",
                    "port": 1521,
                    "database": "PROD",
                    "username": "monitor_user",
                    "password": "your_secure_password",
                    "environment": "production",
                    "enabled": True
                }
            ]
        }
        st.json(example_config)

@st.cache_data(ttl=300)  # Cache for 5 minutes
def collect_all_database_metrics():
    """Collect metrics from all configured databases with caching"""
    
    configs = get_database_configs()
    if not configs:
        return {}
    
    collector = DatabaseMetricsCollector()
    results = {}
    
    for config in configs:
        if config.enabled:
            try:
                metrics = collector.collect_metrics_for_database(config)
                if metrics:
                    results[config.name] = metrics
            except Exception as e:
                st.error(f"Failed to collect metrics for {config.name}: {e}")
    
    return results

def show_real_time_metrics():
    """Show real-time database metrics dashboard"""
    
    st.markdown("## 📊 Real-Time Database Metrics")
    
    configs = get_database_configs()
    if not configs:
        st.warning("⚠️ No databases configured. Please configure databases first.")
        return
    
    # Control buttons
    col1, col2, col3 = st.columns([2, 2, 2])
    
    with col1:
        if st.button("🔄 Refresh Metrics", type="primary"):
            st.cache_data.clear()
    
    with col2:
        auto_refresh = st.checkbox("🔄 Auto-refresh (30s)")
    
    with col3:
        enabled_dbs = [c.name for c in configs if c.enabled]
        st.metric("Enabled Databases", len(enabled_dbs))
    
    # Auto-refresh logic
    if auto_refresh:
        time.sleep(1)  # Small delay
        st.rerun()
    
    # Collect metrics
    with st.spinner("Collecting database metrics..."):
        metrics_data = collect_all_database_metrics()
    
    if not metrics_data:
        st.error("❌ No metrics data available. Check your database configurations and connections.")
        return
    
    # Display metrics for each database
    for db_name, metrics in metrics_data.items():
        show_database_metrics_card(db_name, metrics)

def show_database_metrics_card(db_name: str, metrics: DatabaseMetrics):
    """Display metrics card for a single database"""
    
    # Status indicator
    if metrics.collection_status == "success":
        status_color = "🟢"
        status_text = "Connected"
    else:
        status_color = "🔴"
        status_text = "Error"
    
    with st.expander(f"{status_color} {db_name} - {status_text}", expanded=True):
        
        if metrics.collection_status != "success":
            st.error(f"❌ Collection Error: {metrics.error_message}")
            return
        
        # Key metrics in columns
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("CPU Usage", f"{metrics.cpu_usage_percent:.1f}%")
            st.metric("Active Connections", metrics.active_connections)
        
        with col2:
            st.metric("Memory Usage", f"{metrics.memory_usage_percent:.1f}%") 
            st.metric("Queries/Sec", f"{metrics.queries_per_second:.1f}")
        
        with col3:
            st.metric("Buffer Hit Ratio", f"{metrics.buffer_hit_ratio:.1f}%")
            st.metric("Database Size", f"{metrics.database_size_gb:.1f} GB")
        
        with col4:
            st.metric("Connection Usage", f"{metrics.connection_usage_percent:.1f}%")
            st.metric("Read/Write Ratio", f"{metrics.read_write_ratio:.1f}")
        
        # Performance chart
        show_database_performance_chart(db_name, metrics)

def show_database_performance_chart(db_name: str, metrics: DatabaseMetrics):
    """Show performance chart for a database"""
    
    performance_data = {
        'Metric': ['CPU Usage', 'Memory Usage', 'Connection Usage', 'Buffer Hit Ratio'],
        'Value': [
            metrics.cpu_usage_percent,
            metrics.memory_usage_percent,
            metrics.connection_usage_percent,
            metrics.buffer_hit_ratio
        ]
    }
    
    fig = px.bar(
        performance_data,
        x='Metric',
        y='Value',
        title=f"{db_name} Performance Overview",
        color='Value',
        color_continuous_scale='RdYlGn_r',
        range_color=[0, 100]
    )
    fig.update_layout(height=300, showlegend=False)
    st.plotly_chart(fig, use_container_width=True)

def generate_aws_migration_recommendations():
    """Generate AWS migration recommendations based on collected metrics"""
    
    st.markdown("## 🤖 AWS Migration Recommendations")
    
    if st.button("🚀 Generate Migration Analysis", type="primary"):
        
        # Collect current metrics
        with st.spinner("Analyzing database metrics for AWS migration..."):
            metrics_data = collect_all_database_metrics()
        
        if not metrics_data:
            st.error("❌ No metrics data available for analysis")
            return
        
        # Generate recommendations for each database
        recommendations = {}
        
        for db_name, metrics in metrics_data.items():
            if metrics.collection_status == "success":
                recommendations[db_name] = analyze_database_for_aws(db_name, metrics)
        
        if recommendations:
            st.session_state.optimization_results = recommendations
            st.success(f"✅ Generated AWS migration recommendations for {len(recommendations)} databases!")
            
            # Show summary
            show_migration_recommendations_summary(recommendations)
        else:
            st.warning("⚠️ No successful metrics found to analyze")

def analyze_database_for_aws(db_name: str, metrics: DatabaseMetrics) -> Dict:
    """Analyze a database for AWS migration recommendations"""
    
    # Calculate workload characteristics
    complexity_score = (
        metrics.cpu_usage_percent * 0.3 +
        metrics.memory_usage_percent * 0.3 +
        metrics.connection_usage_percent * 0.2 +
        (100 - metrics.buffer_hit_ratio) * 0.2
    )
    
    # Determine workload type
    if metrics.read_write_ratio > 5:
        workload_type = 'read_heavy'
    elif metrics.read_write_ratio < 0.5:
        workload_type = 'write_heavy'
    elif metrics.queries_per_second > 1000:
        workload_type = 'analytics'
    else:
        workload_type = 'balanced'
    
    # Recommend RDS instance size
    if metrics.memory_total_gb <= 16 and metrics.active_connections <= 100:
        writer_instance = 'db.r5.xlarge'
        writer_vcpu = 4
        writer_memory = 32
        writer_cost = 700
    elif metrics.memory_total_gb <= 32 and metrics.active_connections <= 200:
        writer_instance = 'db.r5.2xlarge'
        writer_vcpu = 8
        writer_memory = 64
        writer_cost = 1400
    elif metrics.memory_total_gb <= 64 and metrics.active_connections <= 400:
        writer_instance = 'db.r5.4xlarge'
        writer_vcpu = 16
        writer_memory = 128
        writer_cost = 2800
    else:
        writer_instance = 'db.r5.8xlarge'
        writer_vcpu = 32
        writer_memory = 256
        writer_cost = 5600
    
    # Multi-AZ recommendation
    multi_az = (metrics.cpu_usage_percent > 70 or 
                metrics.connection_usage_percent > 60 or
                metrics.database_size_gb > 100)
    
    if multi_az:
        writer_cost *= 2
    
    # Read replica recommendations
    if workload_type == 'read_heavy':
        reader_count = 3
        reader_instance = 'db.r5.xlarge'
        reader_cost_each = 700
    elif workload_type == 'analytics':
        reader_count = 2
        reader_instance = 'db.r5.2xlarge'
        reader_cost_each = 1400
    elif workload_type == 'balanced' and metrics.queries_per_second > 100:
        reader_count = 1
        reader_instance = 'db.r5.large'
        reader_cost_each = 350
    else:
        reader_count = 0
        reader_instance = None
        reader_cost_each = 0
    
    total_reader_cost = reader_count * reader_cost_each
    total_monthly_cost = writer_cost + total_reader_cost
    
    return {
        'workload_analysis': {
            'complexity_score': complexity_score,
            'cpu_intensity': metrics.cpu_usage_percent,
            'memory_intensity': metrics.memory_usage_percent,
            'io_intensity': min(100, metrics.queries_per_second / 10),
            'workload_type': workload_type,
            'read_scaling_factor': metrics.read_write_ratio
        },
        'writer_optimization': {
            'instance_class': writer_instance,
            'specs': type('obj', (object,), {'vcpu': writer_vcpu, 'memory_gb': writer_memory}),
            'multi_az': multi_az,
            'monthly_cost': writer_cost
        },
        'reader_optimization': {
            'count': reader_count,
            'instance_class': reader_instance,
            'monthly_cost_per_replica': reader_cost_each,
            'total_monthly_cost': total_reader_cost
        },
        'cost_analysis': {
            'monthly_breakdown': {
                'writer': writer_cost,
                'readers': total_reader_cost,
                'total': total_monthly_cost
            },
            'reserved_instance_options': {
                '1_year': {
                    'monthly_cost': total_monthly_cost * 0.65,
                    'total_savings': total_monthly_cost * 0.35 * 12
                },
                '3_year': {
                    'monthly_cost': total_monthly_cost * 0.45,
                    'total_savings': total_monthly_cost * 0.55 * 36
                }
            }
        },
        'optimization_score': min(100, 100 - complexity_score + metrics.buffer_hit_ratio)
    }

def show_migration_recommendations_summary(recommendations: Dict):
    """Show summary of migration recommendations"""
    
    st.markdown("### 📋 Migration Recommendations Summary")
    
    # Summary metrics
    total_environments = len(recommendations)
    total_monthly_cost = sum([rec['cost_analysis']['monthly_breakdown']['total'] 
                             for rec in recommendations.values()])
    total_readers = sum([rec['reader_optimization']['count'] 
                        for rec in recommendations.values()])
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("📊 Environments", total_environments)
    
    with col2:
        st.metric("✍️ Writer Instances", total_environments)
    
    with col3:
        st.metric("📖 Read Replicas", total_readers)
    
    with col4:
        st.metric("💰 Monthly Cost", f"${total_monthly_cost:,.0f}")
    
    # Detailed recommendations table
    recommendations_data = []
    for env_name, rec in recommendations.items():
        writer = rec['writer_optimization']
        reader = rec['reader_optimization']
        
        recommendations_data.append({
            'Environment': env_name,
            'Writer Instance': writer['instance_class'],
            'Writer Specs': f"{writer['specs'].vcpu} vCPU, {writer['specs'].memory_gb} GB RAM",
            'Reader Count': reader['count'],
            'Reader Instance': reader['instance_class'] if reader['count'] > 0 else 'None',
            'Multi-AZ': '✅ Yes' if writer['multi_az'] else '❌ No',
            'Monthly Cost': f"${rec['cost_analysis']['monthly_breakdown']['total']:,.0f}",
            'Optimization Score': f"{rec['optimization_score']:.0f}/100"
        })
    
    df = pd.DataFrame(recommendations_data)
    st.dataframe(df, use_container_width=True)

# Import your existing RDS analysis functions here
# from your_existing_module import show_enhanced_recommendations_dashboard

def main():
    """Main Streamlit application"""
    
    st.title("🔄 Database Migration Analyzer")
    st.markdown("Comprehensive analysis of on-premise databases with AWS RDS migration recommendations")
    
    # Sidebar navigation
    st.sidebar.title("🧭 Navigation")
    
    pages = {
        "⚙️ Database Configuration": show_database_configuration,
        "📊 Real-Time Metrics": show_real_time_metrics,
        "🤖 AWS Migration Analysis": generate_aws_migration_recommendations,
        "📋 Migration Recommendations": lambda: show_existing_recommendations(),
        "📈 Migration Planning": lambda: show_migration_planning()
    }
    
    selected_page = st.sidebar.selectbox("Choose a page", list(pages.keys()))
    
    # Show package status in sidebar
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 📦 Package Status")
    
    packages_status = {
        "Oracle": "✅" if ORACLE_AVAILABLE else "❌",
        "MySQL": "✅" if MYSQL_AVAILABLE else "❌", 
        "SQL Server": "✅" if SQLSERVER_AVAILABLE else "❌",
        "System Metrics": "✅" if PSUTIL_AVAILABLE else "❌"
    }
    
    for package, status in packages_status.items():
        st.sidebar.write(f"{status} {package}")
    
    if not all([ORACLE_AVAILABLE, MYSQL_AVAILABLE, SQLSERVER_AVAILABLE]):
        st.sidebar.warning("⚠️ Install missing packages for full functionality")
    
    # Run selected page
    try:
        pages[selected_page]()
    except Exception as e:
        st.error(f"Error running page: {e}")
        st.exception(e)

def show_existing_recommendations():
    """Show existing RDS recommendations from your original code"""
    
    if 'optimization_results' in st.session_state and st.session_state.optimization_results:
        st.markdown("## 📋 Detailed Migration Recommendations")
        
        # Import and use your existing recommendation functions
        # For now, showing a placeholder
        st.info("🔧 Integrate your existing recommendation functions here")
        
        # Example: show_enhanced_recommendations_dashboard()
        
    else:
        st.info("💡 Run the AWS Migration Analysis first to generate recommendations")

def show_migration_planning():
    """Show migration planning tools"""
    
    st.markdown("## 📈 Migration Planning")
    st.info("🚧 Migration planning tools will be implemented here")
    
    # Add your existing migration planning code here

if __name__ == "__main__":
    main()
"""
Database Migration Script
Adds missing columns to trades table for analytics
"""
import sqlite3
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def migrate_trades_table(db_path="trading_bot.db"):
    """Add missing columns to trades table"""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get existing columns
        cursor.execute("PRAGMA table_info(trades)")
        existing_columns = {row[1] for row in cursor.fetchall()}
        logger.info(f"Existing columns: {existing_columns}")
        
        # Define columns to add
        columns_to_add = [
            ("position_size", "REAL DEFAULT 0"),
            ("exit_price", "REAL DEFAULT 0"),
            ("pnl", "REAL DEFAULT 0"),
            ("closed_at", "TIMESTAMP"),
            ("leverage", "INTEGER DEFAULT 1"),
            ("risk_reward_ratio", "REAL DEFAULT 0"),
        ]
        
        # Add missing columns
        for column_name, column_type in columns_to_add:
            if column_name not in existing_columns:
                try:
                    cursor.execute(f'ALTER TABLE trades ADD COLUMN {column_name} {column_type}')
                    logger.info(f"✅ Added column: {column_name}")
                except sqlite3.OperationalError as e:
                    logger.warning(f"⚠️ Column {column_name} already exists or error: {e}")
        
        # Rename 'size' to 'position_size' if needed (by copying data)
        if 'size' in existing_columns and 'position_size' in existing_columns:
            try:
                cursor.execute("UPDATE trades SET position_size = size WHERE position_size = 0 OR position_size IS NULL")
                logger.info("✅ Copied 'size' data to 'position_size'")
            except Exception as e:
                logger.error(f"❌ Error copying size data: {e}")
        
        conn.commit()
        
        # Verify changes
        cursor.execute("PRAGMA table_info(trades)")
        columns = cursor.fetchall()
        logger.info("\n📊 Updated trades table schema:")
        for col in columns:
            logger.info(f"  - {col[1]} ({col[2]})")
        
        conn.close()
        logger.info("\n✅ Migration completed successfully!")
        
    except Exception as e:
        logger.error(f"❌ Migration failed: {e}")
        raise

if __name__ == "__main__":
    migrate_trades_table()

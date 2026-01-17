-- Discord Stock Exchange (DSX) Database Schema

-- Core user table
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,          -- Discord user ID
    username TEXT NOT NULL,
    display_name TEXT,
    avatar_url TEXT,
    total_shares INTEGER DEFAULT 1000,    -- Total shares of this user that exist
    shares_available INTEGER DEFAULT 1000, -- Shares not yet bought by anyone
    is_active INTEGER DEFAULT 1,          -- 0 = delisted (left server)
    opted_out INTEGER DEFAULT 0,          -- 1 = user voluntarily opted out
    opt_out_date TIMESTAMP,               -- When they opted out
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Stock pricing data
CREATE TABLE IF NOT EXISTS stocks (
    user_id INTEGER PRIMARY KEY,
    base_price REAL DEFAULT 100.0,        -- Starting price
    current_price REAL DEFAULT 100.0,
    previous_close REAL DEFAULT 100.0,    -- Yesterday's closing price
    daily_high REAL DEFAULT 100.0,
    daily_low REAL DEFAULT 100.0,
    all_time_high REAL DEFAULT 100.0,
    all_time_low REAL DEFAULT 100.0,
    volume_today INTEGER DEFAULT 0,       -- Shares traded today
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- Who owns what shares
CREATE TABLE IF NOT EXISTS portfolios (
    holder_id INTEGER NOT NULL,           -- Who owns the shares
    stock_id INTEGER NOT NULL,            -- Whose stock they own
    shares INTEGER DEFAULT 0,
    avg_buy_price REAL DEFAULT 0.0,       -- Average price paid per share
    locked_until TIMESTAMP,               -- Lockup period after purchase
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (holder_id, stock_id),
    FOREIGN KEY (holder_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (stock_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- Transaction history
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    buyer_id INTEGER,                     -- NULL for sell to market
    seller_id INTEGER,                    -- NULL for IPO/system buys
    stock_id INTEGER NOT NULL,
    shares INTEGER NOT NULL,
    price_per_share REAL NOT NULL,
    total_amount REAL NOT NULL,
    transaction_type TEXT NOT NULL,       -- 'buy', 'sell', 'dividend', 'short', 'short_cover'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (buyer_id) REFERENCES users(user_id),
    FOREIGN KEY (seller_id) REFERENCES users(user_id),
    FOREIGN KEY (stock_id) REFERENCES users(user_id)
);

-- Daily activity metrics for price calculation
CREATE TABLE IF NOT EXISTS activity_metrics (
    user_id INTEGER NOT NULL,
    date DATE NOT NULL,
    messages INTEGER DEFAULT 0,
    reactions_received INTEGER DEFAULT 0,
    unique_reactors INTEGER DEFAULT 0,    -- Unique people who reacted
    voice_minutes INTEGER DEFAULT 0,
    replies_received INTEGER DEFAULT 0,
    mentions_received INTEGER DEFAULT 0,
    PRIMARY KEY (user_id, date),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- Player wallets
CREATE TABLE IF NOT EXISTS wallets (
    user_id INTEGER PRIMARY KEY,
    balance REAL DEFAULT 10000.0,         -- Starting capital: $10,000
    lifetime_earnings REAL DEFAULT 0.0,
    lifetime_dividends REAL DEFAULT 0.0,
    daily_streak INTEGER DEFAULT 0,
    last_daily_claim DATE,
    last_active DATE,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- Price history for charts
CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    price REAL NOT NULL,
    volume INTEGER DEFAULT 0,
    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_transactions_stock ON transactions(stock_id);
CREATE INDEX IF NOT EXISTS idx_transactions_created ON transactions(created_at);
CREATE INDEX IF NOT EXISTS idx_activity_date ON activity_metrics(date);
CREATE INDEX IF NOT EXISTS idx_price_history_user ON price_history(user_id, recorded_at);
CREATE INDEX IF NOT EXISTS idx_portfolios_holder ON portfolios(holder_id);

-- Short positions (borrowed shares sold for profit if price drops)
CREATE TABLE IF NOT EXISTS short_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    holder_id INTEGER NOT NULL,           -- Who is shorting
    stock_id INTEGER NOT NULL,            -- Which stock they're shorting
    shares INTEGER NOT NULL,              -- Number of shares shorted
    entry_price REAL NOT NULL,            -- Price when short was opened
    collateral REAL NOT NULL,             -- Cash locked as margin (150% of position)
    margin_call_price REAL NOT NULL,      -- Price at which margin call triggers
    liquidation_price REAL NOT NULL,      -- Price at which position auto-closes
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (holder_id) REFERENCES users(user_id),
    FOREIGN KEY (stock_id) REFERENCES users(user_id)
);

-- Hedge funds (groups that pool resources)
CREATE TABLE IF NOT EXISTS hedge_funds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    founder_id INTEGER NOT NULL,
    treasury REAL DEFAULT 0.0,            -- Pooled funds
    total_value REAL DEFAULT 0.0,         -- Treasury + portfolio value
    member_count INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (founder_id) REFERENCES users(user_id)
);

-- Hedge fund members
CREATE TABLE IF NOT EXISTS hedge_fund_members (
    fund_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    role TEXT DEFAULT 'member',           -- 'founder', 'manager', 'member'
    contribution REAL DEFAULT 0.0,        -- Total contributed to fund
    share_pct REAL DEFAULT 0.0,           -- Ownership percentage
    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (fund_id, user_id),
    FOREIGN KEY (fund_id) REFERENCES hedge_funds(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

-- Hedge fund portfolios (stocks owned by funds)
CREATE TABLE IF NOT EXISTS hedge_fund_portfolios (
    fund_id INTEGER NOT NULL,
    stock_id INTEGER NOT NULL,
    shares INTEGER DEFAULT 0,
    avg_buy_price REAL DEFAULT 0.0,
    PRIMARY KEY (fund_id, stock_id),
    FOREIGN KEY (fund_id) REFERENCES hedge_funds(id) ON DELETE CASCADE,
    FOREIGN KEY (stock_id) REFERENCES users(user_id)
);

-- Market events
CREATE TABLE IF NOT EXISTS market_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,             -- 'crash', 'boom', 'split', 'dividend_bonus'
    magnitude REAL DEFAULT 1.0,           -- Multiplier (0.5 = 50% crash, 1.5 = 50% boom)
    target_user_id INTEGER,               -- NULL for market-wide, user_id for specific
    description TEXT,
    active_until TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Stock split history
CREATE TABLE IF NOT EXISTS stock_splits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    old_shares INTEGER NOT NULL,          -- Shares before split
    new_shares INTEGER NOT NULL,          -- Shares after split
    split_ratio TEXT NOT NULL,            -- e.g., "2:1", "3:1"
    old_price REAL NOT NULL,
    new_price REAL NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

-- Indexes for new tables
CREATE INDEX IF NOT EXISTS idx_short_positions_holder ON short_positions(holder_id);
CREATE INDEX IF NOT EXISTS idx_short_positions_stock ON short_positions(stock_id);
CREATE INDEX IF NOT EXISTS idx_hedge_fund_members ON hedge_fund_members(user_id);
CREATE INDEX IF NOT EXISTS idx_market_events_active ON market_events(active_until);

CREATE TABLE IF NOT EXISTS market_news (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    news_type TEXT NOT NULL,
    description TEXT NOT NULL,
    impact REAL NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS limit_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    stock_id INTEGER NOT NULL,
    shares INTEGER NOT NULL,
    target_price REAL NOT NULL,
    order_type TEXT NOT NULL, -- 'buy_low', 'sell_high'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id),
    FOREIGN KEY (stock_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS achievements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    achievement_name TEXT NOT NULL,
    description TEXT NOT NULL,
    unlocked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id),
    UNIQUE(user_id, achievement_name)
);

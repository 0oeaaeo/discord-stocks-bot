# 📈 Discord Stock Exchange (DSX)

**Turn your friends into assets!**

Welcome to the **Discord Stock Exchange**, a chaotic and fun economy bot where **YOU** are the stock market. Every member of your Discord server becomes a tradable asset. Their stock price fluctuates based on their activity—chatting, voice time, and reactions.

Buy low, sell high, and dominate the leaderboard!

## 🚀 Features

*   **👥 Human Stock Market:** Every user is a stock. New members IPO instantly upon joining!
*   **📊 Dynamic Pricing:** Stock prices move in real-time based on user activity. The more active they are, the higher their value!
*   **💸 Trading System:** Buy and sell shares of your friends (or enemies).
*   **💼 Portfolio Management:** Track your holdings, net worth, and daily gains/losses.
*   **🏆 Leaderboards:** Compete to be the richest trader on the server.
*   **📉 Opt-Out Mechanics:** Don't want to be traded? Opt out and watch your value decay into oblivion (spooky!).
*   **🤖 Admin & Economy:** robust economy system to keep inflation in check (maybe).

## 🛠️ Installation

### Prerequisites

*   Python 3.8+
*   A Discord Bot Token (get one from the [Discord Developer Portal](https://discord.com/developers/applications))

### Setup

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/0oeaaeo/discord-stocks-bot.git
    cd discord-stocks-bot
    ```

2.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

3.  **Configure environment:**
    Create a `.env` file in the root directory:
    ```env
    DISCORD_TOKEN=your_discord_bot_token_here
    ```

4.  **Run the bot:**
    ```bash
    python bot.py
    ```

## 🎮 How to Play

### Basic Commands

*   `$ticker @user` (or `$stock`) - Check a user's current stock price and trends.
*   `$buy @user <amount>` - Buy shares of a user. Invest in the active ones!
*   `$sell @user <amount>` - Sell your shares to cash out.
*   `$portfolio` (or `$pf`) - View your current holdings and net worth.
*   `$balance` (or `$bal`) - Check your cash balance.
*   `$leaderboard` - See who's winning at capitalism.

### The Golden Rule

**Activity = Value.**
If a user stops chatting or vanishes, their stock price will plummet. If they are the life of the party, their stock goes to the moon! 🚀

## 🤝 Contributing

Got a cool idea for a market crash event? Or a new way to calculate value? Pull requests are welcome!

1.  Fork the repo.
2.  Create your feature branch (`git checkout -b feature/market-crash`).
3.  Commit your changes.
4.  Push to the branch.
5.  Open a Pull Request.

## 📄 License

Distributed under the MIT License. See `LICENSE` for more information.

---
*Disclaimer: This is a game. No real money is involved. Please do not try to pay your rent with DSX coins.*

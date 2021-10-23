# Unibot
## Bot to constantly monitor and buy new potentially "quality" Uniswapv2 Listings

### Components:

a) mask.sol is a basic implementation of the Uniswap v2 router to allow you to swap tokens without sending transactions directly to the Uniswap router (which other bots are constantly monitoring). Deploy this using remix.ethereum.org from the address that will be doing the trading and input the contract address into the main script.

b) main.py is the script that is constantly running looking for snipable tokens. For this to run properly you need:

1. Git clone the entire repo for package dependencies in venv
2. An etherscan API key
3. An infura/quiknode https endpoint
4. A deployed mask.sol contract address
5. Highly recommended you use botfather on telegram to make a new bot and chat with it to keep track of everything. Input the bot token and chat id into the script, it uses https://github.com/eternnoir/pyTelegramBotAPI

You can mess around with the parameters and trade sizes based on liquidity, also slippage. 

### Ape logic:

1. Unibot only buys verified etherscan contracts (bytecode typically scam, unless contract address was announced before)
2. We screen out *most* honeypot contracts that have bad transfer functions or are otherwise malicious by have it read the code
3. We only buy projects with <X amount of holders at listing and liquidity within a certain range
4. We only buy projects that have a telegram group, not channels, or verifiable unique website in the contract (too hit or miss with others)

### Potential improvements:

1. Look at the mempool. Current function will only allow for the sniping of listings in the block after the listing
2. Expand to Sushi, any other Uniswapv2 like router. Can use a similar structure across PancakeSwap as well
3. Submit transactions normally as well as Flashbots to up chance of being included in a block
                                
## Disclaimers: This is purely beta software and if you dont know what you are doing and updating the logic you could lose money. Use at your own risk. This is not being maintained. 

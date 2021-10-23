from web3 import Web3
import uniswap as uni
import requests
import time
import csv
import pandas as pd
pd.options.mode.chained_assignment = None  # default='warn'
import telebot
import numpy as np
import json
from bs4 import BeautifulSoup
import urllib.request
from datetime import datetime
import warnings
import re

global v2address
global etherscanAPI
global node_provider
global address
global pk
global TOKEN
global chat_id

v2address = '0x5c69bee701ef814a2b6a3edd4b1652cb9cc5aa6f' # uniswapv2 factory address

################################################### INPUT VARIABLES ###################################################
etherscanAPI = '' # etherscanAPI key
node_provider = '' # infura/quicknode https:// endpoint
address = '' # address that will be doing the trading
pk = '' # private key of the trading address
deployedcontractaddress = '' # middleman contract to execute the swap
TOKEN = '' # telegram bot token
chat_id = '' # telegram chat id
wei = 1000000000000000000
#############g##########################################################################################################

# old web scraping helper to get around etherscan 403 error
class AppURLopener(urllib.request.FancyURLopener):
    version = "Mozilla/5.0"

# get recently added contracts from the uniswapv2 factory url
def getUniswapcontracts():
    while True:
        try:
            internalurl = 'https://api.etherscan.io/api?module=account&action=txlistinternal&address='+v2address+'&sort=desc&apikey='+etherscanAPI
            uniswap = requests.get(internalurl).json()
            uniswap = uniswap['result']
            uniswapdf = pd.DataFrame.from_dict(uniswap).head(10) # revise to latest n additions
            uniswapdf = uniswapdf[uniswapdf.errCode != 'Out of gas'] # get rid of contracts that didn't go through
            uniswapcontracts = uniswapdf['contractAddress'].to_list()
            break
        except AttributeError:
            print('etherscan slow............')
            time.sleep(1)
        except json.decoder.JSONDecodeError:
            print('etherscan slow............')
            time.sleep(1)
    return uniswapcontracts

# get basic token data from the uniswap contract address
def getTokendata(contractaddress):
    retrycount = 0
    while True:
        try:
            ERC20url = 'https://api.etherscan.io/api?module=account&action=tokentx&address=' + contractaddress + '&startblock=0&endblock=999999999&sort=asc&apikey=' + etherscanAPI
            uniswap = requests.get(ERC20url).json()
            if int(uniswap['status']) == 1:
                uniswap = uniswap['result']
                uniswapdf = pd.DataFrame.from_dict(uniswap)
                uniswapdf = uniswapdf[uniswapdf['tokenSymbol'] != 'WETH'] # get rid of the corresponding WETH txs
                uniswapdf = uniswapdf[uniswapdf['tokenSymbol'] != 'UNI-V2'] # get rid of the corresponding UNI-V2 txs
                name = uniswapdf['tokenName'].unique()[0] # get the token added
                symbol = uniswapdf['tokenSymbol'].unique()[0]
                tokenaddress = uniswapdf['contractAddress'].unique()[0]
                if len(name) == 0 or len(symbol) == 0:
                    if retrycount <= 10: # retry up to 10 times if some tokendata couldnt be pulled properly
                        print(ERC20url)
                        print('not pulling in right, check ERC url')
                        retrycount = retrycount + 1
                        time.sleep(1)
                    else:
                        valid = 0
                        return [valid,np.nan,np.nan,np.nan]
                        break
                else:
                    valid = 1
                    return [valid,name,symbol,tokenaddress]
                    break
            else:
                print(ERC20url)
                print('no transactions yet, check ERC url')
                if retrycount <= 10:
                    retrycount = retrycount + 1
                    time.sleep(1)
                else:
                    valid = 0
                    return [valid, np.nan, np.nan, np.nan]
                    break
        except json.decoder.JSONDecodeError:
            print('etherscan slow............')
            print(ERC20url)
            time.sleep(1)
        except (KeyError,IndexError) as e:
            print('dont think token is unique....')
            print(ERC20url)
            valid = 0
            return [valid,np.nan,np.nan,np.nan]
        except ValueError:
            print(ERC20url)
            print('contact failure, probably didnt go through check ERC url')
            valid = 0
            return [valid,np.nan,np.nan,np.nan]

# determine if the contract is verified by etherscan (i.e. not byte code and we can see it), auto-generated, or potentially malicious and pull source code
def determineandGetContract(tokenaddress):
    while True:
        try:
            verifiedurl = 'https://api.etherscan.io/api?module=contract&action=getabi&address=' + tokenaddress + '&apikey=' + etherscanAPI
            response = requests.get(verifiedurl)
            verified = response.json()
            if int(verified['status']) == 1:
                verify = 1
                print('contract verified!')
                sourcecodeurl = 'https://api.etherscan.io/api?module=contract&action=getsourcecode&address='+tokenaddress+'&apikey='+etherscanAPI
                response = requests.get(sourcecodeurl)
                sourcecode = response.json()['result']
                sourcecodestr = ','.join(str(v) for v in sourcecode)
                if 'vittominacori' in sourcecodestr:
                    tokenNotGenerated = 0
                    print('contract was auto-generated...')
                else:
                    tokenNotGenerated = 1
                    print('contract was properly created!')
                malicious = ['givePermissions', 'mint(address miner, uint256 _value) external onlyOwner', 'initMint',
                             'Must only be called by the owner (MasterChef)', 'owner = (0x',
                             '_from == owner || _to == owner || _from == ',
                             'checkAddress', 'doInit', 'modifier pooladdress', 'require(!add',
                             'require((sender == _safeOwner)||(recipient == _unirouter)','_balances[acc] = 0',
                             'if(from != address(0) && newun == address(0)) newun = to','function clearCNDAO()']
                if any(x in sourcecodestr for x in malicious):
                    safe = 0
                    print('malicious contract..........')
                else:
                    safe = 1
                    print('contract is safe!')
                    code = sourcecode[0]['SourceCode']
                break
            else:
                print('contract not verified...')
                verify = 0
                tokenNotGenerated = 0
                safe = 0
            break
        except json.decoder.JSONDecodeError:
            print('etherscan slow.............')
            time.sleep(1)
    try:
        contractdata = [verify, tokenNotGenerated,safe,code]
        return contractdata
    except UnboundLocalError:
        contractdata = [verify, tokenNotGenerated,safe]
        return contractdata

# see how much eth is in the pool
def pool_liquidity(contractaddress):
    weth = Web3.toChecksumAddress("0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2")
    tokenaddress = Web3.toChecksumAddress(contractaddress)
    uniswap_wrapper = uni.Uniswap(tokenaddress,private_key=None,web3=w3, version=2)
    pool_liq = uniswap_wrapper.get_token_balance(weth)/(10**18)
    if pool_liq < 1:
        pool_liq = 0
    return pool_liq

# get how many people hold the token currently
def getHolders(tokenaddress):
    warnings.filterwarnings("ignore", category=DeprecationWarning) # using old scraper to bypass etherscan 403 error
    while True:
        try:
            holdersurl = 'https://etherscan.io/token/' + tokenaddress
            opener = AppURLopener()
            response = opener.open(holdersurl)
            soup = BeautifulSoup(response, features="html.parser")
            divparent = soup.find('div', {"id": "ContentPlaceHolder1_tr_tokenHolders"})
            holderstext = divparent.text
            holderstext = holderstext.replace(',', '')
            holders = [int(s) for s in holderstext.split() if s.isdigit()][0]
            break
        except:
            print(holdersurl)
            print('check holders..... etherscan running slow? or blocked')
            time.sleep(3)
    return holders

# get telegram group from contract if it exists and check to make sure it's real
def getTgGroup(tokenaddress):
    while True:
        try:
            sourcecodeurl = 'https://api.etherscan.io/api?module=contract&action=getsourcecode&address='+tokenaddress+'&apikey='+etherscanAPI
            response = requests.get(sourcecodeurl)
            sourcecode = response.json()['result']
            sourcecodestr = ','.join(str(v) for v in sourcecode)
            urls = re.findall(r'(https?://\S+)', sourcecodestr)
            urls = [w.replace('\\r\\n', '') for w in urls]
            notchannelcounter = 0
            for u in range(0, len(urls)):
                if 't.me' in urls[u]:
                    opener = AppURLopener()
                    response = opener.open(urls[u])
                    soup = BeautifulSoup(response, features="html.parser")
                    if 'Preview channel' in soup.text:
                        notchannelcounter = notchannelcounter - 1
                        print('telegram link is a channel...')
                    else:
                        if 'View in Telegram' in soup.text:
                            print('telegram link is not a channel or fake!')
                            notchannelcounter = notchannelcounter + 2
                        else:
                            notchannelcounter = notchannelcounter - 1
                            print('fake telegram group...')
            if notchannelcounter > 0:
                tggroup = 1  # fast track the buy to not run diff
                print('at least one group in contract was legit!')
                return tggroup
            if notchannelcounter == 0:
                tggroup = 0
                print('proper socials couldnt be found...')
                return tggroup
            else:
                tggroup = -1
                print('socials fake...')
                return tggroup
            break
        except json.decoder.JSONDecodeError:
            print('etherscan slow.............')
            time.sleep(1)

# get potential links on website
def getTokenLinks(tokenaddress,contractaddress):
    tokenaddress = tokenaddress.lower()
    contractaddress = contractaddress.lower()
    unitradelink = 'https://app.uniswap.org/#/swap?outputcurrency=' + tokenaddress
    unitradelink2 = 'https://app.uniswap.org/#/swap?inputcurrency=' + tokenaddress
    uniswapinfolink = 'https://info.uniswap.org/token/' + tokenaddress
    uniswapinfopoollink = 'https://info.uniswap.org/pair/' + contractaddress
    ethertokenlink = 'https://etherscan.io/token/' + tokenaddress
    etheraddresslink = 'https://etherscan.io/address/' + tokenaddress
    dextlink = 'https://www.dextools.io/app/uniswap/pair-explorer/' + contractaddress
    return [unitradelink,unitradelink2,uniswapinfolink,uniswapinfopoollink,ethertokenlink,etheraddresslink,dextlink]

# get if website is valid or not and if there are socials (returns 1 if website valid, 2 if website and non ANN telegram)
def getWebsite(tokenname,tokenaddress,contractaddress):
    warnings.filterwarnings("ignore", category=DeprecationWarning)  # using old scraper to bypass etherscan 403 error
    if 't.me' in tokenname:  # its just a telegram group
        print('website is just a telegram group...')
        ready = 0
    else:
        # format tokenname as a url
        if 'https://' in tokenname or 'http://' in tokenname:
            url = tokenname
        else:
            url = 'https://' + tokenname
        try:
            site_ping = requests.get(url)  # get status
        except:
            print('invalid website...')
            return 0
        if site_ping.status_code < 300:  # website is up
            opener = AppURLopener()
            response = opener.open(url)
            soup = BeautifulSoup(response, features="html.parser")
            if len(soup.text) > 50:  # there is real content on the website
                print('valid website!')
                links = []
                tokenlinks = []
                for link in soup.findAll('a'):  # get all links on website
                    link = link.get('href')
                    try:
                        if 't.me/' in link:  # find the telegram links
                            links.append(link.lower())
                        if 'uniswap' in link or 'etherscan' in link:  # find links to verify token
                            tokenlinks.append(link.lower())
                    except:
                        continue
                possiblelinks = getTokenLinks(tokenaddress, contractaddress)
                poolliq = pool_liquidity(contractaddress)
                # if low liq just ape on a telegram group, dont need verification
                if (poolliq <= 10) and (len(links) > 0):
                    notchannelcounter = 0
                    print('social links found on website!')
                    for l in range(0, len(links)):
                        response = opener.open(links[l])
                        soup = BeautifulSoup(response, features="html.parser")
                        if 'Preview channel' in soup.text:
                            print('telegram link is a channel...')
                        else:
                            print('telegram link is not a channel!')
                            notchannelcounter = notchannelcounter + 1
                    if notchannelcounter > 0:
                        ready = 2  # fast track the buy to not run diff
                    if notchannelcounter == 0:
                        print('only telegram is annoucement only... SCAM')
                        ready = 0
                # if more liq, need to verify its correct contract
                if (poolliq > 10) and (len(links) > 0):
                    if (any(e in possiblelinks for e in
                                          tokenlinks)):
                        print('social links found on website and contract link is correct!')
                        notchannelcounter = 0
                        for l in range(0, len(links)):
                            response = opener.open(links[l])
                            soup = BeautifulSoup(response, features="html.parser")
                            if 'Preview channel' in soup.text:
                                print('telegram link is a channel...')
                            else:
                                print('telegram link is not a channel!')
                                notchannelcounter = notchannelcounter + 1
                        if notchannelcounter > 0:
                            ready = 2  # fast track the buy to not run diff
                        if notchannelcounter == 0:
                            print('only telegram is annoucement only... SCAM')
                            ready = 0
                    else:
                        print('cant properly verify any of the links...')
                        ready = 0
                if len(links) == 0:
                    print('couldnt find socials on website...')
                    contractsocials = getTgGroup(tokenaddress)
                    ready = 1 + contractsocials  # it is 2, if socials exist in contract so can still fast track, 1 means no socials
            else:
                print('invalid website...')
                ready = 0
        else:
            print('invalid website...')
            ready = 0
    return ready

# test listing against 6 key measures (visible contract, legit creation, safe code, pool liquidity, holders, and website)
def testContract(contractaddress,tokenname,tokenaddress,contractdetails,minliquidity,maxliquidity,minholders,maxholders):
    testvariables = contractdetails[:3] # first three tests on the contract
    # only bother running if other contract tests have been positive
    if sum(testvariables) == len(testvariables):
        poolliq = pool_liquidity(contractaddress)
        if poolliq >= minliquidity and poolliq <= maxliquidity:
            print('there is enough liquidity!')
            testvariables.append(1)
        else:
            print('there is not enough liquidity...')
            testvariables.append(0)
    else:
        print('dont bother checking pool liquidity...')
        testvariables.append(0)

    # holders test, only bother running if other tests have been positive
    if sum(testvariables) == len(testvariables):
        numholders = getHolders(tokenaddress)
        if numholders >= minholders and numholders <= maxholders:
            print('appropriate number of holders!')
            testvariables.append(1)
        else:
            print('not an appropriate number of holders...')
            testvariables.append(0)
    else:
        print('dont bother checking how many holders...')
        testvariables.append(0)

    # if the name is a website, check to make sure that the website exists
    # only bother running if other tests have been positive
    if sum(testvariables) == len(testvariables):
        if '.' in tokenname:
            websitevalid = getWebsite(tokenname,tokenaddress,contractaddress)
            testvariables.append(websitevalid)
        else:
            print('N/A, not a website!')
            testvariables.append(1+getTgGroup(tokenaddress)) # it wasn't a website, buy maybe if tg group in the contract

    # last step, check against other contracts to make sure its not a scam
    # refers to seperate function for this, only run if other tests have been positive AND if SOCIALS weren't located on website/contract
    diff = sum(testvariables) - len(testvariables)
    if diff <= 0: # failed a test or nothing to fast track it
        print('dont bother checking if contract is scammy...')
        testvariables.append(0)
    if diff == 1: # if website checks out or if there is a legit telegram group in contract, autobuy
        testvariables.append(1) # just buy it if watching already

    return testvariables

# if we buy, determine how much we should based on current pool liquidity in WETH
def determineTradeSize(liquidity):
    if liquidity >= 20:
        tradeSize = 1
    if liquidity > 10 and liquidity < 20:
        tradeSize = (1/20) * liquidity
    if liquidity > 2 and liquidity <= 10:
        tradeSize = (1/10) * liquidity
    if liquidity <= 2:
        tradeSize = .2
    return tradeSize

# initiate the trade
def makeTrade(tokenaddress,ethamount,slippage):
    tokenaddress = Web3.toChecksumAddress(tokenaddress)
    ethamount = int(ethamount * wei)
    nonce = w3.eth.getTransactionCount(my_address)
    data = contract.encodeABI(fn_name="BOP", args=[
            tokenaddress, slippage])
    tx = {
        'nonce': nonce,
        'to': Web3.toChecksumAddress(deployedcontractaddress),
        'value': ethamount,
        'gas': 250000,
        'gasPrice': int(2.5 * (w3.eth.gasPrice)),
        'from': my_address,
        'data': data
    }

    try:
        signed_tx = w3.eth.account.signTransaction(tx, pk)

    except:
        print("Failed to created signed TX!")

    try:
        receipt = w3.eth.waitForTransactionReceipt(w3.toHex(w3.keccak(signed_tx.rawTransaction)))
        print(str(receipt))
        ethamount = ethamount / wei
        print(str(ethamount) + ' ETH of ' + str(tokenaddress) + ' was GREAT SUCCESS, ' + w3.toHex(
            w3.keccak(signed_tx.rawTransaction)))

    except:
        print("Failed sending TX!")
        print(str(receipt))
        ethamount = ethamount / wei
        print(str(ethamount) + ' ETH of ' + str(tokenaddress) + ' was ALADEENED, ' + w3.toHex(
            w3.keccak(signed_tx.rawTransaction)))

# if trade was made, send a message on TG
def sendMessage(tokeninfo,amount,contractaddress):
    while True:
        try:
            # Send to TG
            bot = telebot.TeleBot(TOKEN,parse_mode=None)
            textmsg = str(amount) + ' ETH worth of ' + str(tokeninfo[1]) + ', ' + str(tokeninfo[2]) + ' purchased'
            etherlink = 'https://etherscan.io/token/' + tokeninfo[3]
            dextlink = 'https://www.dextools.io/app/uniswap/pair-explorer/' + contractaddress

            bot.send_message(chat_id, textmsg)
            bot.send_message(chat_id, etherlink)
            bot.send_message(chat_id, dextlink)
            break
        except Exception as e:
            print(e)
            time.sleep(3)

# if code was broken for some reason, send TG message with exception
def sendErrorMessage(error):
    while True:
        try:
            # Send to TG
            bot = telebot.TeleBot(TOKEN, parse_mode=None)
            textmsg = 'Bot error '+str(error)
            bot.send_message(chat_id, textmsg)
            break
        except:
            time.sleep(3)

def main():
    ##### Get most recent contracts which have been added to Uniswap V2 #####
    contracts = getUniswapcontracts()
    # read contracts and compare files, if file doesn't exist (i.e. first time) make it
    try:
        with open('contracts.csv', 'r') as my_file:
            reader = csv.reader(my_file)
            oldcontracts = list(reader)[0]
        newcontracts = np.setdiff1d(contracts, oldcontracts).tolist()
    except FileNotFoundError:
        with open('contracts.csv', 'w', newline='') as myfile:
            wr = csv.writer(myfile, quoting=csv.QUOTE_ALL)
            wr.writerow(contracts)
        newcontracts = []
    # If there was a new contract(s), run it through the filters
    if len(newcontracts) > 0:
        for c in range(0,len(newcontracts)):
            print('-------------------------------------------------')
            naive_dt = datetime.now()
            print(naive_dt)
            print('Uniswap Contract Address: '+ str(newcontracts[c]))
            # Make sure it's possible to pull basic data from the contract; if NAN, quit now
            tokendata = getTokendata(newcontracts[c])
            if tokendata[0] == 1: # basic info exists
                print('Name: ' + str(tokendata[1]))
                print('Symbol: ' + str(tokendata[2]))
                print('Token Address: ' + str(tokendata[3]))
                contractdetails = determineandGetContract(tokendata[3])  # get contract details
                testResults = testContract(contractaddress=newcontracts[c],tokenname=tokendata[1],tokenaddress=tokendata[3],
                                           contractdetails=contractdetails,minliquidity=.5,maxliquidity=40,minholders=1,
                                           maxholders=7)
                if sum(testResults) > len(testResults): # we ape
                    poolliq = pool_liquidity(newcontracts[c])
                    print('BUY ME')
                    # Store the token we just bought so we don't buy it again accidently
                    try:
                        with open('bottokens.csv', 'r') as my_file:
                            reader = csv.reader(my_file)
                            oldbought = list(reader)[0]
                        oldbought.append(tokendata[3])
                        with open('bottokens.csv', 'w', newline='') as myfile:
                            wr = csv.writer(myfile, quoting=csv.QUOTE_ALL)
                            wr.writerow(oldbought)
                    except FileNotFoundError:
                        with open('bottokens.csv', 'w', newline='') as myfile:
                            wr = csv.writer(myfile, quoting=csv.QUOTE_ALL)
                            wr.writerow([tokendata[3]])
                    # Determine trade size and make the swap
                    tradesize = determineTradeSize(poolliq)
                    makeTrade(Web3.toChecksumAddress(tokendata[3]), tradesize, my_address, pk,slippage=5)
                    print('Trade was successfully made!')
                    print('-------------------------------------------------')
                    sendMessage(tokendata, tradesize, newcontracts[c])
                    print('-------------------------------------------------')
                if sum(testResults) < len(testResults): # failed some part of the test
                    print('DONT BUY ME')
                    print('-------------------------------------------------')
            else: # basic token info doesn't exist or it's a Y.finance clone
                print('Wasnt able to pull basic info on contract, invalid')
                print('-------------------------------------------------')
        # Write file to update it
        with open('contracts.csv', 'w', newline='') as myfile:
            wr = csv.writer(myfile, quoting=csv.QUOTE_ALL)
            wr.writerow(contracts)

if __name__ == '__main__':
    # Setup Infura
    w3 = Web3(Web3.HTTPProvider(node_provider))
    print('Web 3 is connected: ' + str(w3.isConnected()))
    # Connect to Uniswap
    my_address = Web3.toChecksumAddress(address)
    uniconnect = uni.Uniswap(my_address, pk, web3=w3, version=2)
    # Get middleman smart contract to obfuscate tx
    with open('uniswap.txt') as json_file:
        data = json.load(json_file)  # middleman swap contract ABI
    contract_address = Web3.toChecksumAddress(deployedcontractaddress)
    contract = w3.eth.contract(contract_address, abi=data)
    # Print current eth balance
    print(str(uniconnect.get_eth_balance() / (wei) + ' ETH in wallet at start'))
    while True:
        try:
            main()
            time.sleep(3)
        except Exception as e:
            sendErrorMessage(e)
            time.sleep(10)
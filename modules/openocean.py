from typing import Dict

import aiohttp
import requests
from loguru import logger
from web3 import Web3
from config import OPENOCEAN_CONTRACT, BASE_TOKENS
from utils.gas_checker import check_gas
from utils.helpers import retry
from .account import Account


class OpenOcean(Account):
    def __init__(self, account_id: int, private_key: str) -> None:
        super().__init__(account_id=account_id, private_key=private_key, chain="base")

    async def get_tx_data(self) -> Dict:
        tx = {
            "chainId": await self.w3.eth.chain_id,
            "from": self.address,
            "nonce": await self.w3.eth.get_transaction_count(self.address),
        }

        return tx

    async def build_transaction(self, from_token: str, to_token: str, amount: int, slippage: float):
        url = "https://open-api.openocean.finance/v3/8453/swap_quote"

        params = {
            "inTokenAddress": Web3.to_checksum_address(from_token),
            "outTokenAddress": Web3.to_checksum_address(to_token),
            "amount": float(amount),
            "gasPrice": float(round(Web3.from_wei(await self.w3.eth.gas_price, "gwei"), 1)),
            "slippage": slippage,
            "account": self.address,
        }

        if OPENOCEAN_CONTRACT["use_ref"]:
            params.update({
                "referrer": Web3.to_checksum_address("0x1c7ff320ae4327784b464eed07714581643b36a7"),
                "referrerFee": 1
            })

        async with aiohttp.ClientSession() as session:
            response = await session.get(url=url, params=params)

            transaction_data = await response.json()

            return transaction_data

    @retry
    @check_gas
    async def swap(
            self,
            from_token: str,
            to_token: str,
            min_amount: float,
            max_amount: float,
            decimal: int,
            slippage: int,
            all_amount: bool,
            min_percent: int,
            max_percent: int
    ):
        amount_wei, amount, balance = await self.get_amount(
            from_token,
            min_amount,
            max_amount,
            decimal,
            all_amount,
            min_percent,
            max_percent
        )

        logger.info(
            f"[{self.account_id}][{self.address}] Swap on OpenOcean – {from_token} -> {to_token} | {amount} {from_token}"
        )

        from_token = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE" if from_token == "ETH" else BASE_TOKENS[from_token]
        to_token = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE" if to_token == "ETH" else BASE_TOKENS[to_token]

        transaction_data = await self.build_transaction(
            from_token,
            to_token,
            amount,
            slippage,
        )

        if from_token != "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE":
            await self.approve(amount_wei, from_token, OPENOCEAN_CONTRACT["router"])

        tx_data = await self.get_tx_data()
        tx_data.update(
            {
                "to": Web3.to_checksum_address(transaction_data["data"]["to"]),
                "data": transaction_data["data"]["data"],
                "value": int(transaction_data["data"]["value"]),
            }
        )

        signed_txn = await self.sign(tx_data)

        txn_hash = await self.send_raw_transaction(signed_txn)

        await self.wait_until_tx_finished(txn_hash.hex())

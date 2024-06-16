# Copyright © 2024 Taoshi Inc (edits by sirouk)

import os
from dotenv import load_dotenv

from typing import List, Dict

import json
import requests

from utils.storage_util import StorageUtil
from utils.time_util import TimeUtil


class OrderUtil:
	#URL = "http://127.0.0.1:80/miner-positions"
	URL = os.getenv("MINER_POSITIONS_ENDPOINT_URL")


	MINER_POSITIONS_DIR = "miner_positions/"
	MINER_POSITIONS_FILE = "miner_positions"
	MINER_POSITION_LOCATION = MINER_POSITIONS_DIR + MINER_POSITIONS_FILE

	FLAT = "FLAT"

	@staticmethod
	def get_current_miner_positions(exchange = ""):
		try:
			miner_positions_data = StorageUtil.get_file(OrderUtil.MINER_POSITION_LOCATION + "_" + exchange + ".json")
			miner_positions_data = json.loads(miner_positions_data)
		except FileNotFoundError:
			miner_positions_data = None
		return miner_positions_data


	@staticmethod
	def get_new_miner_positions(api_key):
		# Pass API key
		data = {
			'api_key': api_key
		}
		# Convert the Python dictionary to JSON format
		json_data = json.dumps(data)
		# Set the headers to specify that the content is in JSON format
		headers = {
			'Content-Type': 'application/json',
		}
		# Make the GET request with JSON data
		return requests.get(OrderUtil.URL, data=json_data, headers=headers)


	@staticmethod
	def get_flattened_order_map(data):
		flattened_order_map = {}
		unique_order_uuids = set()
		
		# Default sort (maybe)
		# Get indexes entries from data
		#sorted_muids = data.keys()


		# Sort muids based on the sorting key
		def sort_key(muid):
			_ps = data[muid]
			
			# Default to Taoshi Dashboard 30 Day Returns
			total_return = _ps.get('thirty_day_returns', 0)
			
			# Other rank sort methods
			#total_return = _ps.get('thirty_day_returns', 0) + sum(_ps.get('thirty_day_returns_augmented', []))
			#total_return = sum(_ps.get('thirty_day_returns_augmented', []))
			return total_return
		sorted_muids = sorted(data.keys(), key=sort_key, reverse=True)

		

		_rank = 0
		for _muid in sorted_muids:
			_ps = data[_muid]
			_rank += 1
			
			#print(_ps)
			#quit()

			for _p in _ps["positions"]:
				for order in _p["orders"]:
					order["position_uuid"] = _p["position_uuid"]
					order["position_type"] = _p["position_type"]
					order["net_leverage"] = _p["net_leverage"]
					order["rank"] = _rank
					order["muid"] = _muid
					order["trade_pair"] = _p["trade_pair"]
					flattened_order_map[order["order_uuid"]] = order
					unique_order_uuids.add(order["order_uuid"])

		return flattened_order_map, unique_order_uuids



	@staticmethod
	def get_new_orders(api_key, exchange, logger):
		response = OrderUtil.get_new_miner_positions(api_key)

		# Check if the request was successful (status code 200)
		if response.status_code == 200:
			logger.debug("GET request was successful.")
			new_miner_positions_data = response.json()
		else:
			logger.debug(response.__dict__)
			logger.debug("GET request failed with status code: " + str(response.status_code))

			return None

		# get the response data, if it doesnt exist store it.
		# if it does exist compare it to see if theres any new trades
		# if theres a new order place it in TG

		# safely create the dir if it doesnt exist already
		StorageUtil.make_dir(OrderUtil.MINER_POSITIONS_DIR)

		miner_positions_data = OrderUtil.get_current_miner_positions(exchange)

		if miner_positions_data is None:
			
			logger.info("no miner positions file exists, sending all existing orders.")
			# send in all orders if miner positions data doesn't exist
			old_orders = None
			new_orders, new_order_uuids = OrderUtil.get_flattened_order_map(new_miner_positions_data)
			
			logger.info("updating miner positions file.")
			StorageUtil.write_file(OrderUtil.MINER_POSITION_LOCATION + "_" + exchange + ".json", new_miner_positions_data)
			
			#logger.info(f"new order uuids to send : [{new_order_uuids}]")

			return [new_order for order_uuid, new_order in new_orders.items()], old_orders
		else:
			# compare data against existing and if theres differences send in
			old_orders, order_uuids = OrderUtil.get_flattened_order_map(miner_positions_data)
			new_orders, new_order_uuids = OrderUtil.get_flattened_order_map(new_miner_positions_data)

			#logger.debug(f"new order uuids : [{new_order_uuids}]")
			#logger.debug(f"existing order uuids : [{order_uuids}]")

			logger.info("updating miner positions file.")
			StorageUtil.write_file(OrderUtil.MINER_POSITION_LOCATION + "_" + exchange + ".json", new_miner_positions_data)

			new_order_uuids_to_send = [value for value in new_order_uuids if value not in order_uuids]
			#logger.info(f"new order uuids to send : [{new_order_uuids_to_send}]")

			return [new_orders[order_uuid] for order_uuid in new_order_uuids_to_send], [old_orders[order_uuid] for order_uuid in order_uuids]


	@staticmethod
	def total_leverage_by_position_type(position_uuid, rank_gradient_allocation, rank_override, exchange, logger):	
		
		total_leverage = {'LONG': 0.0, 'SHORT': 0.0}

		miner_positions_data = OrderUtil.get_current_miner_positions(exchange)
		if miner_positions_data is None:
			# If the miner positions data is not available, return an empty dictionary
			logger.error("No miner positions data available.")
			return total_leverage

		# Iterate over each miner's positions to find the matching position_uuid
		found = False
		for miner_data in miner_positions_data.values():
			for position in miner_data.get('positions', []):
				if position.get('position_uuid') == position_uuid:
					found = True
					for order in position.get('orders', []):
						
						# Calculate the trade size
						if rank_override is not None:
							trade_numerator, trade_denominator = rank_gradient_allocation[rank_override]
						else:
							# use historical rank
							trade_numerator, trade_denominator = rank_gradient_allocation[order["rank"]]

						# align leverage with direction
						if order.get('order_type') == 'LONG':
							total_leverage['LONG'] += abs(order.get('leverage', 0.0)) * trade_numerator
						elif order.get('order_type') == 'SHORT':
							total_leverage['SHORT'] += abs(order.get('leverage', 0.0)) * trade_numerator * -1
			if found:
				break  # Break from the outer loop if the position_uuid has been found

		if not found:
			logger.error(f"Position UUID {position_uuid} not found in the dataset.")

		return total_leverage


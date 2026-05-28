#!/bin/bash

kafka-topics.sh --create --topic brand.news.global --bootstrap-server localhost:9092
kafka-topics.sh --create --topic brand.news.regional --bootstrap-server localhost:9092
kafka-topics.sh --create --topic brand.nlp.processed --bootstrap-server localhost:9092
kafka-topics.sh --create --topic brand.alerts.crisis --bootstrap-server localhost:9092

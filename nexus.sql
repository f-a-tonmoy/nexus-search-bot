-- MySQL dump 10.13  Distrib 8.0.44, for Win64 (x86_64)
--
-- Host: 127.0.0.1    Database: my_custom_bot
-- ------------------------------------------------------
-- Server version	8.0.44

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

--
-- Table structure for table `clean_url_engines`
--

DROP TABLE IF EXISTS `clean_url_engines`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `clean_url_engines` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `clean_url_id` bigint NOT NULL,
  `search_term_id` int NOT NULL,
  `search_engine` varchar(32) NOT NULL,
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_engine` (`clean_url_id`,`search_term_id`,`search_engine`),
  KEY `search_term_id` (`search_term_id`),
  CONSTRAINT `clean_url_engines_ibfk_1` FOREIGN KEY (`clean_url_id`) REFERENCES `clean_urls` (`id`),
  CONSTRAINT `clean_url_engines_ibfk_2` FOREIGN KEY (`search_term_id`) REFERENCES `search_terms` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=363 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `clean_urls`
--

DROP TABLE IF EXISTS `clean_urls`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `clean_urls` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `raw_url_id` bigint NOT NULL,
  `search_term_id` int NOT NULL,
  `url` text NOT NULL,
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_clean_url` (`search_term_id`,`url`(512)),
  KEY `raw_url_id` (`raw_url_id`),
  CONSTRAINT `clean_urls_ibfk_1` FOREIGN KEY (`raw_url_id`) REFERENCES `raw_urls` (`id`),
  CONSTRAINT `clean_urls_ibfk_2` FOREIGN KEY (`search_term_id`) REFERENCES `search_terms` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=305 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `raw_urls`
--

DROP TABLE IF EXISTS `raw_urls`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `raw_urls` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `search_term_id` int NOT NULL,
  `search_engine` varchar(32) NOT NULL,
  `page_no` int NOT NULL DEFAULT '1',
  `url` text NOT NULL,
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `search_term_id` (`search_term_id`),
  CONSTRAINT `raw_urls_ibfk_1` FOREIGN KEY (`search_term_id`) REFERENCES `search_terms` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=502 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `search_history`
--

DROP TABLE IF EXISTS `search_history`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `search_history` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `searched_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  `search_term_id` int DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `search_term_id` (`search_term_id`),
  CONSTRAINT `search_history_ibfk_1` FOREIGN KEY (`search_term_id`) REFERENCES `search_terms` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=71 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `search_terms`
--

DROP TABLE IF EXISTS `search_terms`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `search_terms` (
  `id` int NOT NULL AUTO_INCREMENT,
  `term` varchar(512) NOT NULL,
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=4 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `url_frequency`
--

DROP TABLE IF EXISTS `url_frequency`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `url_frequency` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `clean_url_id` bigint NOT NULL,
  `search_term_id` int NOT NULL,
  `term_occurrences` int NOT NULL DEFAULT '0',
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_freq` (`clean_url_id`,`search_term_id`),
  KEY `search_term_id` (`search_term_id`),
  CONSTRAINT `url_frequency_ibfk_1` FOREIGN KEY (`clean_url_id`) REFERENCES `clean_urls` (`id`),
  CONSTRAINT `url_frequency_ibfk_2` FOREIGN KEY (`search_term_id`) REFERENCES `search_terms` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=264 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping routines for database 'my_custom_bot'
--
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2026-04-17 21:21:47

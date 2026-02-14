package com.p2p.vitshare

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.net.wifi.WifiManager
import android.os.Build
import android.os.IBinder
import android.os.Environment
import android.provider.MediaStore
import android.provider.OpenableColumns
import android.util.Log
import android.webkit.MimeTypeMap
import androidx.annotation.RequiresApi
import androidx.core.app.NotificationCompat
import androidx.localbroadcastmanager.content.LocalBroadcastManager
import kotlinx.coroutines.*
import org.json.JSONObject
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream
import java.io.InputStream
import java.io.OutputStream
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import java.util.zip.ZipInputStream

class NetworkService : Service() {

    private val serviceScope = CoroutineScope(Dispatchers.IO + Job())
    private var isRunning = false
    private val pendingSockets = ConcurrentHashMap<String, Socket>()

    // --- Configuration ---
    private val UDP_PORT = 65431
    private val TCP_PORT = 65432
    private val BROADCAST_MAGIC = "c0d3-p2p-share-v1"
    private val TAG = "NetworkService"
    private val BUFFER_SIZE = 4 * 1048576 // 4 MB

    companion object {
        const val ACTION_PEER_DISCOVERED = "com.p2p.vitshare.PEER_DISCOVERED"
        const val ACTION_IP_ADDRESS = "com.p2p.vitshare.IP_ADDRESS"
        const val EXTRA_PEER_NICKNAME = "PEER_NICKNAME"
        const val EXTRA_PEER_IP = "PEER_IP"
        const val EXTRA_IP_ADDRESS = "IP_ADDRESS"
        const val ACTION_SEND_FILE = "com.p2p.vitshare.SEND_FILE"
        const val ACTION_INITIATE_QR_HANDSHAKE = "com.p2p.vitshare.INITIATE_QR_HANDSHAKE"
        const val EXTRA_TARGET_IP = "TARGET_IP"
        const val EXTRA_FILE_URI = "FILE_URI"
        const val ACTION_TRANSFER_RESPONSE = "com.p2p.vitshare.TRANSFER_RESPONSE"
        const val EXTRA_TRANSFER_ID = "TRANSFER_ID"
        const val EXTRA_TRANSFER_ACCEPTED = "TRANSFER_ACCEPTED"
        const val EXTRA_METADATA_JSON = "METADATA_JSON"
        const val ACTION_TRANSFER_UPDATE = "com.p2p.vitshare.TRANSFER_UPDATE"
        const val EXTRA_IS_SENDING = "IS_SENDING"
        const val EXTRA_BYTES_TRANSFERRED = "BYTES_TRANSFERRED"
        const val EXTRA_TOTAL_BYTES = "TOTAL_BYTES"
        const val EXTRA_FILE_NAME = "FILE_NAME"
        const val EXTRA_IS_COMPLETE = "IS_COMPLETE"
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_INITIATE_QR_HANDSHAKE -> {
                val targetIp = intent.getStringExtra(EXTRA_TARGET_IP)
                if (targetIp != null) {
                    serviceScope.launch { initiateQrHandshake(targetIp) }
                }
            }
            ACTION_SEND_FILE -> {
                val targetIp = intent.getStringExtra(EXTRA_TARGET_IP)
                @Suppress("DEPRECATION")
                val fileUri = intent.getParcelableExtra<Uri>(EXTRA_FILE_URI)
                if (targetIp != null && fileUri != null) {
                    serviceScope.launch { sendFile(targetIp, fileUri) }
                }
            }
            ACTION_TRANSFER_RESPONSE -> {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                    val transferId = intent.getStringExtra(EXTRA_TRANSFER_ID)
                    val accepted = intent.getBooleanExtra(EXTRA_TRANSFER_ACCEPTED, false)
                    val metadataJson = intent.getStringExtra(EXTRA_METADATA_JSON)
                    if (transferId != null && metadataJson != null) {
                        handleTransferResponse(transferId, accepted, metadataJson)
                    }
                }
            }
            else -> {
                if (!isRunning) {
                    isRunning = true
                    startForegroundService()
                    startDiscoveryAndServer()
                }
            }
        }
        return START_STICKY
    }

    @RequiresApi(Build.VERSION_CODES.Q)
    private fun handleTransferResponse(transferId: String, accepted: Boolean, metadataJson: String) {
        val socket = pendingSockets.remove(transferId) ?: return
        serviceScope.launch {
            try {
                if (accepted) {
                    socket.outputStream.buffered().writer().apply {
                        write("ACCEPT\n"); flush()
                    }
                    receiveFileFromSocket(socket, metadataJson)
                } else {
                    socket.outputStream.buffered().writer().apply {
                        write("REJECT\n"); flush()
                    }
                    socket.close()
                }
            } catch (e: Exception) {
                socket.close()
            }
        }
    }

    private suspend fun handleIncomingConnection(socket: Socket) = withContext(Dispatchers.IO) {
        try {
            val reader = socket.inputStream.bufferedReader()
            val firstLine = reader.readLine()
            if (firstLine == null) {
                socket.close(); return@withContext
            }

            val metadata = JSONObject(firstLine)
            when (metadata.optString("type")) {
                "qr_handshake" -> {
                    val remoteNickname = metadata.getString("nickname")
                    val remoteIp = socket.inetAddress.hostAddress
                    addPeer(remoteNickname, remoteIp)

                    val myInfo = JSONObject().apply {
                        put("nickname", Build.MODEL)
                        put("ip", getLocalIpAddress())
                        put("device_type", "android")
                    }.toString()
                    socket.outputStream.buffered().writer().apply {
                        write(myInfo + "\n"); flush()
                    }
                    socket.close()
                }
                else -> handleFileReception(socket, firstLine)
            }
        } catch (e: Exception) {
            socket.close()
        }
    }

    private suspend fun handleFileReception(socket: Socket, metadataString: String) = withContext(Dispatchers.IO) {
        try {
            val metadata = JSONObject(metadataString)
            val fileName = metadata.getString("filename")
            val senderName = metadata.getString("sender_nickname")
            val transferId = UUID.randomUUID().toString()
            pendingSockets[transferId] = socket
            val intent = Intent(this@NetworkService, ConfirmationActivity::class.java).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                putExtra("FILE_NAME", fileName)
                putExtra("SENDER_NAME", senderName)
                putExtra("TRANSFER_ID", transferId)
                putExtra("METADATA_JSON", metadataString)
            }
            startActivity(intent)
        } catch (e: Exception) {
            socket.close()
        }
    }

    private suspend fun initiateQrHandshake(targetIp: String) = withContext(Dispatchers.IO) {
        try {
            Socket(targetIp, TCP_PORT).use { socket ->
                val myInfo = JSONObject().apply {
                    put("type", "qr_handshake")
                    put("nickname", Build.MODEL)
                    put("ip", getLocalIpAddress())
                    put("device_type", "android")
                }.toString()

                socket.outputStream.buffered().writer().apply {
                    write(myInfo + "\n"); flush()
                }

                val reader = socket.inputStream.bufferedReader()
                val response = reader.readLine()
                val laptopInfo = JSONObject(response)
                val laptopNickname = laptopInfo.getString("nickname")
                val laptopIp = laptopInfo.getString("ip")
                addPeer(laptopNickname, laptopIp)
            }
        } catch (e: Exception) {
            Log.e(TAG, "QR connection failed: " + e.message)
        }
    }

    private suspend fun sendFile(targetIp: String, fileUri: Uri) = withContext(Dispatchers.IO) {
        val fileName = getFileName(fileUri)
        val fileSize = getFileSize(fileUri)
        if (fileName == null || fileSize == null) {
            return@withContext
        }

        try {
            val itemType = if (fileName.endsWith(".zip")) "directory" else "file"
            val metadata = JSONObject().apply {
                put("filename", fileName)
                put("filesize", fileSize)
                put("type", itemType)
                put("sender_nickname", Build.MODEL)
            }.toString()

            Socket(targetIp, TCP_PORT).use { socket ->
                socket.outputStream.buffered().writer().apply {
                    write(metadata + "\n"); flush()
                }
                val response = socket.inputStream.bufferedReader().readLine()
                if (response != "ACCEPT") {
                    broadcastProgress(true, fileName, 0, fileSize, isComplete = true)
                    return@withContext
                }
                contentResolver.openInputStream(fileUri)?.use { inputStream ->
                    copyStreamWithProgress(inputStream, socket.outputStream, true, fileName, fileSize)
                }
            }
        } catch (e: Exception) {
            broadcastProgress(true, fileName, 0, fileSize, isComplete = true)
        }
    }

    @RequiresApi(Build.VERSION_CODES.Q)
    private suspend fun receiveFileFromSocket(socket: Socket, metadataJson: String) = withContext(Dispatchers.IO) {
        val metadata = JSONObject(metadataJson)
        val fileName = metadata.getString("filename")
        val fileSize = metadata.getLong("filesize")
        val itemType = metadata.getString("type")
        val tempFile = File(cacheDir, fileName)

        try {
            FileOutputStream(tempFile).use { fileOutputStream ->
                copyStreamWithProgress(socket.inputStream, fileOutputStream, false, fileName, fileSize)
            }
            if (itemType == "directory") {
                val folderName = fileName.removeSuffix(".zip")
                unzipWithMediaStore(tempFile, folderName)
            } else {
                moveCacheFileToDownloads(tempFile)
            }
        } catch (e: Exception) {
            broadcastProgress(false, fileName, 0, fileSize, isComplete = true)
        } finally {
            if (tempFile.exists()) tempFile.delete()
            socket.close()
        }
    }

    private suspend fun copyStreamWithProgress(inputStream: InputStream, outputStream: OutputStream, isSending: Boolean, fileName: String, totalBytes: Long) {
        var bytesTransferred: Long = 0
        val buffer = ByteArray(BUFFER_SIZE)
        var lastUpdateTime = 0L
        broadcastProgress(isSending, fileName, 0, totalBytes)
        var bytes = inputStream.read(buffer)
        while (bytes >= 0) {
            outputStream.write(buffer, 0, bytes)
            bytesTransferred += bytes
            val currentTime = System.currentTimeMillis()
            if (currentTime - lastUpdateTime > 200) {
                broadcastProgress(isSending, fileName, bytesTransferred, totalBytes)
                lastUpdateTime = currentTime
            }
            bytes = inputStream.read(buffer)
        }
        broadcastProgress(isSending, fileName, totalBytes, totalBytes, isComplete = true)
    }

    private fun broadcastProgress(isSending: Boolean, fileName: String, bytesTransferred: Long, totalBytes: Long, isComplete: Boolean = false) {
        val intent = Intent(ACTION_TRANSFER_UPDATE).apply {
            putExtra(EXTRA_IS_SENDING, isSending)
            putExtra(EXTRA_FILE_NAME, fileName)
            putExtra(EXTRA_BYTES_TRANSFERRED, bytesTransferred)
            putExtra(EXTRA_TOTAL_BYTES, totalBytes)
            putExtra(EXTRA_IS_COMPLETE, isComplete)
        }
        LocalBroadcastManager.getInstance(this).sendBroadcast(intent)
    }

    @RequiresApi(Build.VERSION_CODES.Q)
    private fun unzipWithMediaStore(zipFile: File, destFolderName: String) {
        val resolver = applicationContext.contentResolver
        ZipInputStream(FileInputStream(zipFile)).use { zis ->
            var zipEntry = zis.nextEntry
            while (zipEntry != null) {
                if (!zipEntry.isDirectory) {
                    val entryName = zipEntry.name
                    val relativePath = "${Environment.DIRECTORY_DOWNLOADS}/$destFolderName/${File(entryName).parent}".trimEnd('/')
                    val fileName = File(entryName).name
                    val values = ContentValues().apply {
                        put(MediaStore.MediaColumns.DISPLAY_NAME, fileName)
                        put(MediaStore.MediaColumns.MIME_TYPE, getMimeType(fileName))
                        put(MediaStore.MediaColumns.RELATIVE_PATH, relativePath)
                    }
                    val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
                    if (uri != null) {
                        resolver.openOutputStream(uri)?.use { zis.copyTo(it) }
                    }
                }
                zis.closeEntry()
                zipEntry = zis.nextEntry
            }
        }
    }

    @RequiresApi(Build.VERSION_CODES.Q)
    private fun moveCacheFileToDownloads(cacheFile: File) {
        val values = ContentValues().apply {
            put(MediaStore.MediaColumns.DISPLAY_NAME, cacheFile.name)
            put(MediaStore.MediaColumns.MIME_TYPE, getMimeType(cacheFile.name))
            put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS)
        }
        val resolver = applicationContext.contentResolver
        val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
        if (uri != null) {
            resolver.openOutputStream(uri)?.use { outputStream ->
                FileInputStream(cacheFile).use { it.copyTo(outputStream) }
            }
        }
        cacheFile.delete()
    }

    private fun addPeer(nickname: String, ip: String) {
        val peerIntent = Intent(ACTION_PEER_DISCOVERED).apply {
            putExtra(EXTRA_PEER_NICKNAME, nickname)
            putExtra(EXTRA_PEER_IP, ip)
        }
        LocalBroadcastManager.getInstance(this@NetworkService).sendBroadcast(peerIntent)
    }

    override fun onDestroy() {
        super.onDestroy()
        isRunning = false
        serviceScope.cancel()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun startForegroundService() {
        createNotificationChannel()
        val n = NotificationCompat.Builder(this, "network_service_channel").setContentTitle("VIT Share Active").setContentText("Listening for devices...").setSmallIcon(R.mipmap.ic_launcher).build()
        startForeground(1, n)
    }

    private fun startDiscoveryAndServer() {
        serviceScope.launch { broadcastPresence() }
        serviceScope.launch { listenForPeers() }
        serviceScope.launch { startFileServer() }

        // Broadcast IP address
        val ipAddress = getLocalIpAddress()
        if (ipAddress != null) {
            val intent = Intent(ACTION_IP_ADDRESS).apply {
                putExtra(EXTRA_IP_ADDRESS, ipAddress)
            }
            LocalBroadcastManager.getInstance(this).sendBroadcast(intent)
        }
    }

    private suspend fun startFileServer() = withContext(Dispatchers.IO) {
        ServerSocket(TCP_PORT).use { serverSocket ->
            while (isRunning) {
                try {
                    val clientSocket = serverSocket.accept()
                    serviceScope.launch { handleIncomingConnection(clientSocket) }
                } catch (e: Exception) {
                    // Prevent crash on socket close
                }
            }
        }
    }

    private suspend fun listenForPeers() = withContext(Dispatchers.IO) {
        DatagramSocket(UDP_PORT).use { socket ->
            val buffer = ByteArray(1024)
            val packet = DatagramPacket(buffer, buffer.size)
            while (isRunning) {
                try {
                    socket.receive(packet)
                    val message = String(packet.data, 0, packet.length)
                    val json = JSONObject(message)
                    if (json.optString("magic") == BROADCAST_MAGIC && json.optString("nickname") != Build.MODEL) {
                        val nickname = json.getString("nickname")
                        val ip = json.getString("ip")
                        val peerIntent = Intent(ACTION_PEER_DISCOVERED).apply {
                            putExtra(EXTRA_PEER_NICKNAME, nickname)
                            putExtra(EXTRA_PEER_IP, ip)
                        }
                        LocalBroadcastManager.getInstance(this@NetworkService).sendBroadcast(peerIntent)
                    }
                } catch (e: Exception) {
                    // Prevent crash on socket close
                }
            }
        }
    }

    private suspend fun broadcastPresence() = withContext(Dispatchers.IO) {
        DatagramSocket().use { socket ->
            socket.broadcast = true
            val myIp = getLocalIpAddress()
            if (myIp == null) {
                return@withContext
            }
            val message = JSONObject().apply {
                put("magic", BROADCAST_MAGIC)
                put("nickname", Build.MODEL)
                put("ip", myIp)
            }.toString().toByteArray()
            val broadcastAddress = InetAddress.getByName("255.255.255.255")
            val packet = DatagramPacket(message, message.size, broadcastAddress, UDP_PORT)
            while (isRunning) {
                try {
                    socket.send(packet)
                } catch (e: Exception) {
                    // Ignore
                }
                delay(3000)
            }
        }
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            getSystemService(NotificationManager::class.java).createNotificationChannel(NotificationChannel("network_service_channel", "Network Service Channel", NotificationManager.IMPORTANCE_DEFAULT))
        }
    }

    fun getLocalIpAddress(): String? {
        try {
            val wifiManager = applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
            @Suppress("DEPRECATION")
            val ipInt = wifiManager.connectionInfo.ipAddress
            return if (ipInt == 0) null else String.format("%d.%d.%d.%d", ipInt and 0xff, ipInt shr 8 and 0xff, ipInt shr 16 and 0xff, ipInt shr 24 and 0xff)
        } catch (e: Exception) {
            return null
        }
    }

    private fun getFileName(uri: Uri): String? {
        if (uri.scheme == "file") {
            return uri.path?.let { File(it).name }
        }
        return contentResolver.query(uri, null, null, null, null)?.use {
            if (it.moveToFirst()) {
                it.getString(it.getColumnIndexOrThrow(OpenableColumns.DISPLAY_NAME))
            } else null
        }
    }

    private fun getFileSize(uri: Uri): Long? {
        if (uri.scheme == "file") {
            return uri.path?.let { File(it).length() }
        }
        return contentResolver.query(uri, null, null, null, null)?.use {
            if (it.moveToFirst()) {
                it.getLong(it.getColumnIndexOrThrow(OpenableColumns.SIZE))
            } else null
        }
    }

    private fun getMimeType(fileName: String): String {
        return MimeTypeMap.getSingleton().getMimeTypeFromExtension(MimeTypeMap.getFileExtensionFromUrl(fileName))
            ?: "application/octet-stream"
    }
}
import javax.imageio.ImageIO;
import javax.swing.*;
import java.awt.*;
import java.awt.event.KeyEvent;
import java.awt.event.KeyListener;
import java.io.IOException;

/**
 * Created by jassiboy on 2/15/2017.
 */
public class Game implements KeyListener {

    public static int xvel = 3;
    public static int Oxvel = 3;
    public static int Oyvel = -3;

    public static void main(String[] args) {
        JFrame frame = new JFrame();
        JPanel panel = new JPanel();
        panel.setPreferredSize(new Dimension(700, 500));
        frame.add(panel);
        frame.setVisible(true);
        frame.setResizable(false);
        frame.pack();
        frame.setDefaultCloseOperation(JFrame.EXIT_ON_CLOSE);


        try {
            Thread.sleep(300);
        } catch (InterruptedException e) {
            e.printStackTrace();
        }

        panel.setFocusable(true);
        panel.addKeyListener(new Game());
        panel.requestFocus();
        int Rxcord = 400;
        int Oxcord = 0;
        int Oycord = 0;
        Image background= null;
        Image boll= null;
        Rectangle Ovalrect=new Rectangle();
        Rectangle Sliderrect=new Rectangle();
        try {
            background = ImageIO.read(Game.class.getResource("images/ram.jpg"));
            boll = ImageIO.read(Game.class.getResource("images/boll.jpg"));
        } catch (IOException e) {
            System.out.println("Unable to load image");;
        }
        while (true) {

            try {
                Thread.sleep(33);
            } catch (InterruptedException e) {
                e.printStackTrace();
            }


            Rxcord = Rxcord + xvel;
            Oxcord = Oxcord + Oxvel;
            Oycord = Oycord + Oyvel;

//        code for collding with walls for oval
            if (Oxcord > 600) {
                Oxcord = 600;
                Oxvel = -13;
            }
            if (Oycord > 400) {
                Oycord = 400;
                Oyvel = -13;
            }
            if (Oxcord < 0) {
                Oxcord = 0;
                Oxvel = 13;
            }
            if (Oycord < 0) {
                Oycord = 0;
                Oyvel = 13;
            }
            //        code for collding with walls for rectangle


            if (Rxcord > 520) {
                xvel = -10;
            }
            if (Rxcord < 0) {
                xvel = 10;
            }
            //      code for collision

            Ovalrect.setBounds(Oxcord,Oycord,100,100);
            Sliderrect.setBounds(Rxcord,400,180,10);

            if (Ovalrect.intersects(Sliderrect)) {
                //hitAudio.play();
                Oyvel=-15;

            }

            Graphics g = panel.getGraphics();
            g.drawImage(background,0, 0, null);
            g.drawImage(boll,Oxcord, Oycord, null);
          //  g.clearRect(0, 0, 700, 500);
            g.setColor(Color.cyan);
            g.fillRect(Rxcord, 400, 180, 10);


           //g.setColor(Color.green);
            //g.fillOval(Oxcord, Oycord, 100, 100);

            g.dispose();
        }
    }

    @Override
    public void keyTyped(KeyEvent e) {

    }

    @Override
    public void keyPressed(KeyEvent e) {
        if (e.getKeyCode() == KeyEvent.VK_RIGHT) {
            Game.xvel = 15;
        } else if (e.getKeyCode() == KeyEvent.VK_LEFT) {
            Game.xvel = -15;

        }
    }

    @Override
    public void keyReleased(KeyEvent e) {

    }
}

